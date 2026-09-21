"""One-command MCP setup. python scripts/setup_mcp.py --list | --print HOST | --install HOST | --check."""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = [sys.executable, "-m", "reaver_mcp.server", "--transport", "stdio"]

HOSTS = ("claude-code", "desktop", "opencode", "kimi", "mcode", "cursor", "windsurf",
           "cline", "codex", "chatgpt", "api", "inspector")

STDIO_JSON = {"command": SERVER[0], "args": SERVER[1:], "cwd": ROOT}


def _print(host):
    if host == "claude-code":
        return "claude mcp add reaver -- %s" % " ".join(SERVER)
    if host == "kimi":
        return "kimi mcp add --transport stdio reaver -- %s" % " ".join(SERVER)
    if host == "desktop":
        return json.dumps({"mcpServers": {"reaver": STDIO_JSON}}, indent=2)
    if host == "opencode":
        return json.dumps({"mcp": {"reaver": {
            "type": "local", "command": SERVER, "enabled": True}}}, indent=2)
    if host in ("cursor", "windsurf", "mcode", "cline"):
        return json.dumps({"mcpServers": {"reaver": STDIO_JSON}}, indent=2)
    if host == "codex":
        return '[mcp_servers.reaver]\ncommand = "%s"\nargs = %s' % (
            SERVER[0].replace("\\", "\\\\"), json.dumps(SERVER[1:]))
    if host == "chatgpt":
        return ("1. deploy MCP with --token (README)"
                " 2. developer mode > Connectors > https://YOUR-HOST/mcp/")
    if host == "api":
        return json.dumps({"mcp_servers": [{
            "type": "url", "url": "https://YOUR-HOST/mcp/",
            "name": "reaver", "authorization_token": "YOUR_TOKEN"}]}, indent=2)
    return "npx @modelcontextprotocol/inspector  (STDIO: %s)" % " ".join(SERVER)


def _merge_json(path, key, value):
    original = None
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            original = fh.read()
        try:
            data = json.loads(original)
        except ValueError:
            data = {}
    data.setdefault(key, {}).update(value[key])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if original is not None:
        with open(path + ".reaver-bak", "w", encoding="utf-8") as fh:
            fh.write(original)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return path


def _home(*parts):
    return os.path.join(os.path.expanduser("~"), *parts)


def _appdata(*parts):
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), *parts)


def _install(host):
    if host == "claude-code":
        cmd = ["claude", "mcp", "add", "reaver", "--"] + SERVER
        print("+ " + " ".join(cmd))
        subprocess.run(cmd, check=True, cwd=ROOT)
        return "claude-code registered (scoped to this project dir)"
    if host == "kimi":
        cmd = ["kimi", "mcp", "add", "--transport", "stdio", "reaver", "--"] + SERVER
        print("+ " + " ".join(cmd))
        subprocess.run(cmd, check=True, cwd=ROOT)
        return "kimi registered; verify with: kimi mcp list"
    if host == "desktop":
        path = _appdata("Claude", "claude_desktop_config.json")
        _merge_json(path, "mcpServers", {"mcpServers": {"reaver": STDIO_JSON}})
        return path + " updated (backup beside it); restart Claude Desktop"
    if host == "opencode":
        path = os.path.join(ROOT, "opencode.json")
        _merge_json(path, "mcp", {"mcp": {"reaver": {
            "type": "local", "command": SERVER, "enabled": True}}})
        return path + " written; restart OpenCode session"
    if host == "mcode":
        path = _home(".minimax", "mcp.json")
        _merge_json(path, "mcpServers", {"mcpServers": {"reaver": STDIO_JSON}})
        return path + " updated (backup beside it); verify with: mcode mcp list"
    if host == "cursor":
        path = _home(".cursor", "mcp.json")
        _merge_json(path, "mcpServers", {"mcpServers": {"reaver": STDIO_JSON}})
        return path + " updated (backup beside it); restart Cursor"
    if host == "windsurf":
        path = _home(".codeium", "windsurf", "mcp_config.json")
        _merge_json(path, "mcpServers", {"mcpServers": {"reaver": STDIO_JSON}})
        return path + " updated (backup beside it); restart Windsurf"
    if host == "cline":
        path = _appdata("Code", "User", "globalStorage", "saoudrizwan.claude-dev",
                        "settings", "cline_mcp_settings.json")
        _merge_json(path, "mcpServers", {"mcpServers": {"reaver": STDIO_JSON}})
        return path + " updated (backup beside it); reload VS Code window"
    if host == "codex":
        path = _home(".codex", "config.toml")
        block = '[mcp_servers.reaver]\ncommand = "%s"\nargs = %s\n' % (
            SERVER[0].replace("\\", "\\\\"), json.dumps(SERVER[1:]))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        current = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        if "[mcp_servers.reaver]" not in current:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(("\n" if current and not current.endswith("\n") else "") + block)
            return path + " appended; restart Codex CLI"
        return path + " already has reaver; nothing changed"
    return "no auto-install for %s:\n%s" % (host, _print(host))


def _check():
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(command=SERVER[0], args=SERVER[1:], cwd=ROOT)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                assert "prospect" in names and "doctor" in names, names
                return names
    return asyncio.run(go())


def main():
    parser = argparse.ArgumentParser(prog="setup_mcp")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--print", dest="show", choices=HOSTS)
    parser.add_argument("--install", choices=HOSTS)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.list:
        print("hosts: " + ", ".join(HOSTS))
    elif args.show:
        print(_print(args.show))
    elif args.install:
        print(_install(args.install))
    elif args.check:
        print("live tools: " + ", ".join(_check()))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
