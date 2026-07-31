import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def ensure_path(path=None):
    return path or CONFIG_FILE


STALE_KEYS = {"force_bind_blacklist", "compat_mode_blacklist", "close_action"}


def load_config(path=None):
    path = ensure_path(path)
    if not os.path.isfile(path):
        return {"apps": [], "rules": [], "nicknames": {}}
    try:
        with open(path) as f:
            data = json.load(f)
        for key in STALE_KEYS:
            data.pop(key, None)
        data.setdefault("apps", [])
        data.setdefault("rules", [])
        data.setdefault("nicknames", {})
        data.setdefault("backend", "edgechromium")
        return data
    except (json.JSONDecodeError, IOError):
        return {"apps": [], "rules": [], "nicknames": {}}


def save_config(config, path=None):
    path = ensure_path(path)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
    os.replace(tmp, path)


def add_rule(config, app_path, adapter_name, adapter_ip):
    config["rules"] = [r for r in config["rules"] if r["app_path"] != app_path]
    config["rules"].append({
        "app_path": app_path,
        "adapter_name": adapter_name,
        "adapter_ip": adapter_ip
    })
    return config


def remove_rule_for_app(config, app_path):
    config["rules"] = [r for r in config["rules"] if r["app_path"] != app_path]
    return config


def get_rules(config):
    return config.get("rules", [])


def get_nicknames(config):
    return config.get("nicknames", {})


def set_nickname(config, system_name, nickname):
    config.setdefault("nicknames", {})
    if nickname:
        config["nicknames"][system_name] = nickname
    else:
        config["nicknames"].pop(system_name, None)
    return config


def get_theme(config):
    return config.get("theme", "dark")


def set_theme(config, theme):
    config["theme"] = theme
    return config


def get_backend(config):
    return config.get("backend", "edgechromium")


def set_backend(config, backend):
    config["backend"] = backend
    return config