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
worktree_ignore:        # dirs to ignore when checking worktree cleanliness
  - node_modules
  - .venv
```

## Usage

```
gbb              # show branches for current repo
gbb --all        # show all repos immediately
gbb -a           # short form
```

| Key | Action |
|-----|--------|
| `j`/`k` or `↑`/`↓` | Navigate branches |
| `Enter` | Select branch (writes path to result file) |
| `/` | Filter branches |
| `a` | Toggle between current repo and all repos |
| `d` | Delete branch (with confirmation for unmerged) |
| `Alt+↑`/`Alt+↓` | Jump between repos |
| `q`/`Esc` | Quit |

## Features

- **Lazy loading** — current repo renders instantly, others load in background
- **Auto-refresh** — table updates every 5 seconds
- **Branch cleanup** — detects deletable branches (merged, squash-merged, upstream gone) and dims them; `d` to delete with smart confirmation
- **Worktree awareness** — shows dirty status, worktree paths, and checks for files before deleting

## Shell wrapper

Selecting a branch with a worktree writes its path to `/tmp/gbb-<uid>-result`. Use a shell wrapper to `cd` there automatically:

```sh
function gbb() { command gbb && cd "$(cat /tmp/gbb-$(id -u)-result)" }
```

## License

MIT
