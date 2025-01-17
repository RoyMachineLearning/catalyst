from typing import List, Any, Dict, Union
from pathlib import Path
import os
import sys
import subprocess
import copy
import shutil
import time
from collections import OrderedDict

import pip
import safitty
import yaml
import json
from tensorboardX import SummaryWriter

from catalyst.utils.misc import merge_dicts


def load_ordered_yaml(
    stream, Loader=yaml.Loader, object_pairs_hook=OrderedDict
):
    """
    Loads `yaml` config into OrderedDict

    Args:
        stream: opened file with yaml
        Loader: base class for yaml Loader
        object_pairs_hook: type of mapping

    Returns:
        dict: configuration
    """
    class OrderedLoader(Loader):
        pass

    def construct_mapping(loader, node):
        loader.flatten_mapping(node)
        return object_pairs_hook(loader.construct_pairs(node))

    OrderedLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
    )
    return yaml.load(stream, OrderedLoader)


def _decode_dict(dictionary: Dict[str, Union[bytes, str]]) -> Dict[str, str]:
    """
    Decode bytes values in the dictionary to UTF-8
    Args:
        dictionary: a dict

    Returns:
        dict: decoded dict
    """
    result = {
        k: v.decode("UTF-8") if type(v) == bytes else v
        for k, v in dictionary.items()
    }
    return result


def get_environment_vars() -> Dict[str, Any]:
    """
    Creates a dictionary with environment variables

    Returns:
        dict: environment variables
    """
    result = {
        "python_version": sys.version,
        "conda_environment": os.environ.get("CONDA_DEFAULT_ENV", ""),
        "pip": pip.__version__,
        "creation_time": time.strftime("%y%m%d.%H:%M:%S"),
        "sysname": os.uname()[0],
        "nodename": os.uname()[1],
        "release": os.uname()[2],
        "version": os.uname()[3],
        "architecture": os.uname()[4],
        "user": os.environ.get("USER", ""),
        "path": os.environ.get("PWD", ""),
    }

    with open(os.devnull, "w") as devnull:
        try:
            git_branch = subprocess.check_output(
                "git rev-parse --abbrev-ref HEAD".split(), stderr=devnull
            ).strip().decode("UTF-8")
            git_local_commit = subprocess.check_output(
                "git rev-parse HEAD".split(), stderr=devnull
            )
            git_origin_commit = subprocess.check_output(
                f"git rev-parse origin/{git_branch}".split(), stderr=devnull
            )

            git = dict(
                branch=git_branch,
                local_commit=git_local_commit,
                origin_commit=git_origin_commit
            )
            result["git"] = _decode_dict(git)
        except subprocess.CalledProcessError:
            pass

    result = _decode_dict(result)
    return result


def dump_config(
    experiment_config: Dict,
    logdir: str,
    configs_path: List[str] = None,
) -> None:
    """
    Saves config and environment in JSON into logdir

    Args:
        experiment_config (dict): experiment config
        logdir (str): path to logdir
        configs_path: path(s) to config
    """
    configs_path = configs_path or []
    configs_path = [
        Path(path) for path in configs_path if isinstance(path, str)
    ]
    config_dir = Path(logdir) / "configs"
    config_dir.mkdir(exist_ok=True, parents=True)

    environment = get_environment_vars()

    safitty.save(experiment_config, config_dir / "_config.json")
    safitty.save(environment, config_dir / "_environment.json")

    for path in configs_path:
        name: str = path.name
        outpath = config_dir / name
        shutil.copyfile(path, outpath)

    config_str = json.dumps(experiment_config, indent=2)
    config_str = config_str.replace("\n", "\n\n")
    environment_str = json.dumps(environment, indent=2)
    environment_str = environment_str.replace("\n", "\n\n")
    with SummaryWriter(config_dir) as writer:
        writer.add_text("config", config_str, 0)
        writer.add_text("environment", environment_str, 0)


def parse_config_args(*, config, args, unknown_args):
    for arg in unknown_args:
        arg_name, value = arg.split("=")
        arg_name = arg_name.lstrip("-").strip("/")

        value_content, value_type = value.rsplit(":", 1)

        if "/" in arg_name:
            arg_names = arg_name.split("/")
            if value_type == "str":
                arg_value = value_content

                if arg_value.lower() == "none":
                    arg_value = None
            else:
                arg_value = eval("%s(%s)" % (value_type, value_content))

            config_ = config
            for arg_name in arg_names[:-1]:
                if arg_name not in config_:
                    config_[arg_name] = {}

                config_ = config_[arg_name]

            config_[arg_names[-1]] = arg_value
        else:
            if value_type == "str":
                arg_value = value_content
            else:
                arg_value = eval("%s(%s)" % (value_type, value_content))
            args.__setattr__(arg_name, arg_value)

    args_exists_ = config.get("args")
    if args_exists_ is None:
        config["args"] = dict()

    for key, value in args._get_kwargs():
        if value is not None:
            if key in ["logdir", "baselogdir"] and value == "":
                continue
            config["args"][key] = value

    return config, args


def parse_args_uargs(args, unknown_args):
    """
    Function for parsing configuration files

    Args:
        args: recognized arguments
        unknown_args: unrecognized arguments

    Returns:
        tuple: updated arguments, dict with config
    """
    args_ = copy.deepcopy(args)

    # load params
    config = {}
    for config_path in args_.configs:
        with open(config_path, "r") as fin:
            if config_path.endswith("json"):
                config_ = json.load(fin, object_pairs_hook=OrderedDict)
            elif config_path.endswith("yml"):
                config_ = load_ordered_yaml(fin)
            else:
                raise Exception("Unknown file format")
        config = merge_dicts(config, config_)

    config, args_ = parse_config_args(
        config=config, args=args_, unknown_args=unknown_args
    )

    # hack with argparse in config
    config_args = config.get("args", None)
    if config_args is not None:
        for key, value in config_args.items():
            arg_value = getattr(args_, key, None)
            if arg_value is None \
                    or (key in ["logdir", "baselogdir"] and arg_value == ""):
                arg_value = value
            setattr(args_, key, arg_value)

    return args_, config


__all__ = [
    "load_ordered_yaml", "get_environment_vars", "dump_config",
    "parse_config_args", "parse_args_uargs"
]
