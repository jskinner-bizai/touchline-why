"""Offline dependency import smoke only; no Agent/client instances or model calls."""
from datetime import datetime, timezone
import faulthandler
from importlib.metadata import version
import json
from pathlib import Path
import sys

faulthandler.dump_traceback_later(30, exit=True)
from agent_framework import Agent
from agent_framework_ollama import OllamaChatClient
import ollama

report = {
    'verifiedAtUtc': datetime.now(timezone.utc).isoformat(),
    'scope': 'Imports only in freshly installed offline venv',
    'versions': {name: version(name) for name in ('agent-framework-core', 'agent-framework-ollama', 'ollama')},
    'classes': [Agent.__module__ + '.' + Agent.__name__, OllamaChatClient.__module__ + '.' + OllamaChatClient.__name__],
    'agentInstances': 0, 'providerClientInstances': 0, 'modelCalls': 0,
}
Path(sys.argv[1]).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
faulthandler.cancel_dump_traceback_later()
print(json.dumps(report, indent=2))
