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
if [ -z "$_real_git" ]; then
  for _candidate in /usr/bin/git /bin/git /usr/local/bin/git; do
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

# reject explicit git environment overrides
if [ -n "${GIT_DIR+x}" ]; then
  printf 'git-wrapper: blocking GIT_DIR override\\n' >&2
  exit 1
fi
if [ -n "${GIT_WORK_TREE+x}" ]; then
  printf 'git-wrapper: blocking GIT_WORK_TREE override\\n' >&2
  exit 1
fi
if [ -n "${GIT_INDEX_FILE+x}" ]; then
  printf 'git-wrapper: blocking GIT_INDEX_FILE override\\n' >&2
  exit 1
fi
if [ -n "${GIT_OBJECT_DIRECTORY+x}" ]; then
  printf 'git-wrapper: blocking GIT_OBJECT_DIRECTORY override\\n' >&2
  exit 1
fi
if [ -n "${GIT_ALTERNATE_OBJECT_DIRECTORIES+x}" ]; then
  printf 'git-wrapper: blocking GIT_ALTERNATE_OBJECT_DIRECTORIES override\\n' >&2
  exit 1
fi
if [ -n "${GIT_COMMON_DIR+x}" ]; then
  printf 'git-wrapper: blocking GIT_COMMON_DIR override\\n' >&2
  exit 1
fi

export DEVELOPER_DIR=""

_global_no_pager=0

require_current_worktree() {
  if [ -z "$_worktree" ]; then
    return 0
  fi

  if [ ! -d "$_worktree" ]; then
    printf 'git-wrapper: configured worktree does not exist: %s\\n' "$_worktree" >&2
    exit 1
  fi

  _resolved_worktree=$(cd "$_worktree" && pwd -P)
  _cwd=$(pwd -P)
  case "$_cwd" in
    "$_resolved_worktree" | "$_resolved_worktree"/*)
      ;;
    *)
      printf 'git-wrapper: command must run inside worktree %s\\n' "$_resolved_worktree" >&2
      exit 1
      ;;
  esac
}

check_expected_branch() {
  if [ -z "$_expected_branch" ]; then
    return 0
  fi

  if [ -z "$_worktree" ]; then
    printf 'git-wrapper: ORCHESTRATOR_RUN_BRANCH set but ORCHESTRATOR_RUN_WORKTREE is not set\\n' >&2
    exit 1
  fi

  _current_branch=$("$_real_git" -C "$_worktree" rev-parse --abbrev-ref HEAD)
  if [ "$_current_branch" != "$_expected_branch" ]; then
    printf 'git-wrapper: expected branch %s but current branch is %s\\n' "$_expected_branch" "$_current_branch" >&2
    exit 1
  fi
}

reject_path_arg() {
  _path="$1"
  case "$_path" in
    /*)
      printf 'git-wrapper: absolute path arguments are blocked: %s\\n' "$_path" >&2
      exit 1
      ;;
    ../*|*/../*|*'/../'*)
      printf 'git-wrapper: path arguments may not escape the worktree: %s\\n' "$_path" >&2
      exit 1
      ;;
    ..)
      printf 'git-wrapper: path argument is outside the worktree: %s\\n' "$_path" >&2
      exit 1
      ;;
    ~*)
      printf 'git-wrapper: path arguments may not use ~: %s\\n' "$_path" >&2
      exit 1
      ;;
  esac
}

validate_status() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --short|-s|--branch|-b|--untracked-files|--untracked-files=*|--verbose|-v|-vv)
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
      --output=*|--output|-o|--work-tree|--work-tree=*|--git-dir|--git-dir=*)
        printf 'git-wrapper: option is blocked for git status: %s\\n' "$1" >&2
        exit 1
        ;;
      -*)
        printf 'git-wrapper: unknown git status option: %s\\n' "$1" >&2
        exit 1
        ;;
      *)
        reject_path_arg "$1"
        shift
        ;;
    esac
  done
}

validate_diff() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --stat|--name-only|--name-status|--cached|--patch|--no-patch|--color|--no-color)
        shift
        ;;
      -U*|--unified=*)
        shift
        ;;
      --output|--output=*)
        printf 'git-wrapper: blocked option for git diff: %s\\n' "$1" >&2
        exit 1
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
        printf 'git-wrapper: unknown git diff option: %s\\n' "$1" >&2
        exit 1
        ;;
      *)
        reject_path_arg "$1"
        shift
        ;;
    esac
  done
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
        printf 'git-wrapper: unknown git add option: %s\\n' "$1" >&2
        exit 1
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
        printf 'git-wrapper: unknown git restore option: %s\\n' "$1" >&2
        exit 1
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
        printf 'git-wrapper: blocked git commit option: --amend\\n' >&2
        exit 1
        ;;
      -m|--message)
        if [ "$#" -lt 2 ]; then
          printf 'git-wrapper: git commit %s requires a value\\n' "$1" >&2
          exit 1
        fi
        shift 2
        ;;
      --no-verify)
        printf 'git-wrapper: blocked git commit option: --no-verify\\n' >&2
        exit 1
        ;;
      --message=*|-a|--all|--no-edit|--allow-empty|--allow-empty-message|--dry-run|-n)
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
        printf 'git-wrapper: unknown git commit option: %s\\n' "$1" >&2
        exit 1
        ;;
      *)
        reject_path_arg "$1"
        shift
        ;;
    esac
  done
}

validate_log() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --oneline|--graph|--decorate|--no-pager|--date=*|--pretty=*|--max-count=*|--author=*|--name-only|--name-status)
        shift
        ;;
      -n)
        if [ "$#" -lt 2 ]; then
          printf 'git-wrapper: git log %s requires a value\\n' "$1" >&2
          exit 1
        fi
        shift 2
        ;;
      -n* )
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
        printf 'git-wrapper: unknown git log option: %s\\n' "$1" >&2
        exit 1
        ;;
      *)
        # Log references are not required to resolve to files.
        shift
        ;;
    esac
  done
}

validate_show() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --stat|--name-only|--name-status|--patch|--no-patch|--pretty=*|--no-color|--color)
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
        printf 'git-wrapper: unknown git show option: %s\\n' "$1" >&2
        exit 1
        ;;
      *)
        reject_path_arg "$1"
        shift
        ;;
    esac
  done
}

validate_rev_parse() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --abbrev-ref|--verify|--short|--is-inside-work-tree|--show-toplevel)
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
        printf 'git-wrapper: unknown git rev-parse option: %s\\n' "$1" >&2
        exit 1
        ;;
      *)
        reject_path_arg "$1"
        shift
        ;;
    esac
  done
}

validate_ls_files() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --stage|--cached|--modified|--others|--deleted|-s|-m|-c|-d|--)
        if [ "$1" = -- ]; then
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
        printf 'git-wrapper: unknown git ls-files option: %s\\n' "$1" >&2
        exit 1
        ;;
      *)
        reject_path_arg "$1"
        shift
        ;;
    esac
  done
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
      printf 'git-wrapper: blocked global git option: %s\\n' "$1" >&2
      exit 1
      ;;
    --*)
      printf 'git-wrapper: unsupported global option: %s\\n' "$1" >&2
      exit 1
      ;;
    -*)
      printf 'git-wrapper: unsupported global option: %s\\n' "$1" >&2
      exit 1
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
    printf 'git-wrapper: blocked git subcommand: %s\\n' "$_cmd" >&2
    exit 1
    ;;
esac

if [ "$_global_no_pager" -eq 1 ]; then
  exec "$_real_git" --no-pager "$_cmd" "$@"
fi

exec "$_real_git" "$_cmd" "$@"
