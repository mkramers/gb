# gbb

A TUI for browsing git branches across multiple repos. Shows recent branches, worktree status, ahead/behind counts, and lets you quickly jump to a branch's directory.

## Install

```
uv tool install .
```

## Config

Create `~/.config/gbb/config.yaml`:

```yaml
recent_days: 14
repos:
  - ~/projects/repo-a
  - ~/projects/repo-b
```

## Usage

```
gbb
```

| Key | Action |
|-----|--------|
| `j`/`k` | Navigate branches |
| `Enter` | Select branch |
| `/` | Filter branches |
| `a` | Toggle between current repo and all repos |
| `Alt+↑`/`Alt+↓` | Jump between repos |
| `q`/`Esc` | Quit |

Selecting a branch with a worktree writes its path to `/tmp/gbb-<uid>-result`. Use a shell wrapper to `cd` there automatically:

```sh
function gbb() { command gbb && cd "$(cat /tmp/gbb-$(id -u)-result)" }
```

## License

MIT
