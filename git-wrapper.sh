#!/usr/bin/env sh
# Wrapper to enforce safe git usage inside agent run worktrees.
# shellcheck shell=sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

_original_path=${PATH-}
_filtered_path=""
_first=1
_IFS=$IFS
IFS=:
for _candidate in $_original_path; do
  if [ "$_candidate" = "$SCRIPT_DIR" ]; then
    continue
  fi
  if [ -z "$_candidate" ]; then
    continue
  fi
  if [ "$_first" -eq 1 ]; then
    _filtered_path="$_candidate"
    _first=0
  else
    _filtered_path="$_filtered_path:$_candidate"
  fi
done
IFS=$_IFS

_real_git=$(PATH="$_filtered_path" command -v git 2>/dev/null || true)
if [ "$_real_git" = "/usr/bin/git" ] && [ -x /Library/Developer/CommandLineTools/usr/bin/git ]; then
  _real_git=/Library/Developer/CommandLineTools/usr/bin/git
fi
if [ -z "$_real_git" ]; then
  for _candidate in /Library/Developer/CommandLineTools/usr/bin/git /usr/bin/git /bin/git /usr/local/bin/git; do
    if [ -x "$_candidate" ]; then
      _real_git="$_candidate"
      break
    fi
  done
fi
if [ -z "$_real_git" ] || [ ! -x "$_real_git" ]; then
  printf 'git-wrapper: unable to locate real git executable\\n' >&2
  exit 1
fi

_worktree="${ORCHESTRATOR_RUN_WORKTREE-}"
_expected_branch="${ORCHESTRATOR_RUN_BRANCH-}"

explain_security_restriction() {
  _message="$1"
  printf 'git-wrapper: %s\\n' "$_message" >&2
  printf 'git-wrapper: this wrapper protects orchestrator run worktrees by keeping git operations scoped to the current run branch/worktree and blocking options that can escape the sandbox, override git metadata, invoke host tools, write outside allowed paths, or bypass review hooks.\\n' >&2
  printf 'git-wrapper: use ordinary read-only commands inside the worktree, pathspecs after "--", "git restore" for reverting files, and normal "git commit" without --amend/--no-verify. Do not bypass the wrapper; adjust the task or ask for human guidance if a legitimate command is blocked.\\n' >&2
  exit 1
}

# reject explicit git environment overrides
if [ -n "${GIT_DIR+x}" ]; then
  explain_security_restriction "blocking GIT_DIR override"
fi
if [ -n "${GIT_WORK_TREE+x}" ]; then
  explain_security_restriction "blocking GIT_WORK_TREE override"
fi
if [ -n "${GIT_INDEX_FILE+x}" ]; then
  explain_security_restriction "blocking GIT_INDEX_FILE override"
fi
if [ -n "${GIT_OBJECT_DIRECTORY+x}" ]; then
  explain_security_restriction "blocking GIT_OBJECT_DIRECTORY override"
fi
if [ -n "${GIT_ALTERNATE_OBJECT_DIRECTORIES+x}" ]; then
  explain_security_restriction "blocking GIT_ALTERNATE_OBJECT_DIRECTORIES override"
fi
if [ -n "${GIT_COMMON_DIR+x}" ]; then
  explain_security_restriction "blocking GIT_COMMON_DIR override"
fi
unset GIT_EXTERNAL_DIFF

if [ -d /Library/Developer/CommandLineTools ]; then
  export DEVELOPER_DIR=/Library/Developer/CommandLineTools
else
  unset DEVELOPER_DIR
fi
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1
if [ -z "${GIT_AUTHOR_NAME-}" ]; then
  export GIT_AUTHOR_NAME="Orchestrator Agent"
fi
if [ -z "${GIT_AUTHOR_EMAIL-}" ]; then
  export GIT_AUTHOR_EMAIL="orchestrator@local"
fi
if [ -z "${GIT_COMMITTER_NAME-}" ]; then
  export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
fi
if [ -z "${GIT_COMMITTER_EMAIL-}" ]; then
  export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
fi

_global_no_pager=0

require_current_worktree() {
  if [ -z "$_worktree" ]; then
    return 0
  fi

  if [ ! -d "$_worktree" ]; then
    explain_security_restriction "configured worktree does not exist: $_worktree"
  fi

  _resolved_worktree=$(cd "$_worktree" && pwd -P)
  _cwd=$(pwd -P)
  case "$_cwd" in
    "$_resolved_worktree" | "$_resolved_worktree"/*)
      ;;
    *)
      explain_security_restriction "command must run inside worktree $_resolved_worktree"
      ;;
  esac
}

check_expected_branch() {
  if [ -z "$_expected_branch" ]; then
    return 0
  fi

  if [ -z "$_worktree" ]; then
    explain_security_restriction "ORCHESTRATOR_RUN_BRANCH set but ORCHESTRATOR_RUN_WORKTREE is not set"
  fi

  _current_branch=$("$_real_git" -C "$_worktree" rev-parse --abbrev-ref HEAD)
  if [ "$_current_branch" != "$_expected_branch" ]; then
    explain_security_restriction "expected branch $_expected_branch but current branch is $_current_branch"
  fi
}

reject_path_arg() {
  _path="$1"
  case "$_path" in
    /*)
      explain_security_restriction "absolute path arguments are blocked: $_path"
      ;;
    ../*|*/../*|*'/../'*)
      explain_security_restriction "path arguments may not escape the worktree: $_path"
      ;;
    ..)
      explain_security_restriction "path argument is outside the worktree: $_path"
      ;;
    ~*)
      explain_security_restriction "path arguments may not use ~: $_path"
      ;;
  esac
}

reject_read_only_option() {
  _cmd="$1"
  _option="$2"
  case "$_option" in
    --git-dir|--git-dir=*|--work-tree|--work-tree=*|--output|--output=*|--config|--config=*|--config-env|--config-env=*)
      explain_security_restriction "blocked option for git $_cmd: $_option"
      ;;
    --ext-diff|--textconv|--external-diff)
      explain_security_restriction "blocked option for git $_cmd: $_option"
      ;;
    --exclude-from|--exclude-from=*|--recurse-submodules|--recurse-submodules=*)
      explain_security_restriction "blocked option for git $_cmd: $_option"
      ;;
    --git-path|--git-path=*|--git-common-dir|--absolute-git-dir|--resolve-git-dir|--resolve-git-dir=*|--shared-index-path)
      explain_security_restriction "blocked option for git $_cmd: $_option"
      ;;
    --path-format|--path-format=absolute)
      explain_security_restriction "blocked option for git $_cmd: $_option"
      ;;
  esac
}

validate_read_only_args() {
  _cmd="$1"
  shift
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --)
        shift
        while [ "$#" -gt 0 ]; do
          reject_path_arg "$1"
          shift
        done
        break
        ;;
      -*)
        reject_read_only_option "$_cmd" "$1"
        shift
        ;;
      *)
        # Read-only commands accept revisions and pathspecs in the same position.
        # Only pathspecs after `--` are treated as filesystem paths.
        shift
        ;;
    esac
  done
}

validate_status() {
  validate_read_only_args status "$@"
}

validate_diff() {
  validate_read_only_args diff "$@"
}

validate_add() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -A|--all|--intent-to-add|--interactive|-p|--patch|--verbose|-v|-u|--update|--chmod=*)
        shift
        ;;
      --)
        shift
        while [ "$#" -gt 0 ]; do
          reject_path_arg "$1"
          shift
        done
        break
        ;;
      -*)
        explain_security_restriction "unknown git add option: $1"
        ;;
      *)
        reject_path_arg "$1"
        shift
        ;;
    esac
  done
}

validate_restore() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --staged|--worktree|--source|--patch|--theirs|--ours|-s|-W|--)
        if [ "$1" = -- ] ; then
          shift
          while [ "$#" -gt 0 ]; do
            reject_path_arg "$1"
            shift
          done
          break
        fi
        shift
        ;;
      -*)
        explain_security_restriction "unknown git restore option: $1"
        ;;
      *)
        reject_path_arg "$1"
        shift
        ;;
    esac
  done
}

validate_commit() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --amend)
        explain_security_restriction "blocked git commit option: --amend"
        ;;
      -m|--message)
        if [ "$#" -lt 2 ]; then
          printf 'git-wrapper: git commit %s requires a value\\n' "$1" >&2
          exit 1
        fi
        shift 2
        ;;
      --no-verify)
        explain_security_restriction "blocked git commit option: --no-verify"
        ;;
      -n)
        explain_security_restriction "blocked git commit option: -n"
        ;;
      --message=*|-a|--all|--no-edit|--allow-empty|--allow-empty-message|--dry-run)
        shift
        ;;
      --)
        shift
        while [ "$#" -gt 0 ]; do
          reject_path_arg "$1"
          shift
        done
        break
        ;;
      -*)
        explain_security_restriction "unknown git commit option: $1"
        ;;
      *)
        reject_path_arg "$1"
        shift
        ;;
    esac
  done
}

validate_log() {
  validate_read_only_args log "$@"
}

validate_show() {
  validate_read_only_args show "$@"
}

validate_rev_parse() {
  validate_read_only_args rev-parse "$@"
}

validate_ls_files() {
  validate_read_only_args ls-files "$@"
}

if [ "$#" -eq 0 ]; then
  exec "$_real_git"
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-pager)
      _global_no_pager=1
      shift
      ;;
    --git-dir|--git-dir=*|--work-tree|--work-tree=*)
      explain_security_restriction "blocked global git option: $1"
      ;;
    --*)
      explain_security_restriction "unsupported global option: $1"
      ;;
    -*)
      explain_security_restriction "unsupported global option: $1"
      ;;
    *)
      _cmd=$1
      shift
      break
      ;;
  esac
done

if [ -z "${_cmd-}" ]; then
  _cmd=$1
  shift || true
fi

require_current_worktree
check_expected_branch

case "$_cmd" in
  status)
    validate_status "$@"
    ;;
  diff)
    validate_diff "$@"
    ;;
  add)
    validate_add "$@"
    ;;
  restore)
    validate_restore "$@"
    ;;
  commit)
    validate_commit "$@"
    ;;
  log)
    validate_log "$@"
    ;;
  show)
    validate_show "$@"
    ;;
  rev-parse)
    validate_rev_parse "$@"
    ;;
  ls-files)
    validate_ls_files "$@"
    ;;
  *)
    explain_security_restriction "blocked git subcommand: $_cmd"
    ;;
esac

if [ "$_global_no_pager" -eq 1 ]; then
  exec "$_real_git" --no-pager "$_cmd" "$@"
fi

exec "$_real_git" "$_cmd" "$@"
