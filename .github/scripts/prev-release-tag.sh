#!/usr/bin/env bash
# .github/scripts/prev-release-tag.sh <plugin> <version>
#
# Reads newline-separated tag names on stdin and prints the greatest
# `<plugin>--v<strict-semver>` tag that is strictly lower than <version>, or
# nothing when there is no such tag. Exit 0 on success.
#
# <version> is validated against the strict SemVer 2.0.0 grammar (no leading
# zeros on numeric identifiers, no build metadata). On an invalid version,
# prints an `::error::` line to stderr and exits 2 -- this script is the
# single source of the version grammar; nothing else re-validates it.
#
# Filtering: a candidate tag must match the exact `<plugin>--v` prefix (this
# drops `src/*` markers, legacy `v0.0.x` tags and foreign-plugin tags) and its
# version part must itself be strict semver (this drops non-strict tags like
# a leading-zero version). Precedence follows SemVer 2.0.0 section 11:
# numeric identifiers compare numerically, a numeric identifier always has
# lower precedence than an alphanumeric one, and a release has higher
# precedence than any of its own pre-releases.
set -eo pipefail

usage() {
  echo "usage: prev-release-tag.sh <plugin> <version>" >&2
  exit 64
}

[ $# -eq 2 ] || usage

PLUGIN=$1
VERSION=$2

NUMID='(0|[1-9][0-9]*)'
ALNUMID='[0-9]*[a-zA-Z-][0-9a-zA-Z-]*'
PREID="(${NUMID}|${ALNUMID})"
SEMVER_RE="^${NUMID}\.${NUMID}\.${NUMID}(-${PREID}(\.${PREID})*)?\$"

is_strict_semver() {
  [[ "$1" =~ $SEMVER_RE ]]
}

if ! is_strict_semver "$VERSION"; then
  echo "::error::'$VERSION' is not a strict SemVer 2.0.0 version (MAJOR.MINOR.PATCH[-PRERELEASE], no leading zeros, no build metadata)." >&2
  exit 2
fi

# Splits "$1" (a validated strict-semver string) into CORE_MAJOR, CORE_MINOR,
# CORE_PATCH and PRERELEASE (empty string when there is none).
split_version() {
  local v="$1" core pre
  core="${v%%-*}"
  if [[ "$v" == *-* ]]; then
    pre="${v#*-}"
  else
    pre=""
  fi
  IFS='.' read -r CORE_MAJOR CORE_MINOR CORE_PATCH <<<"$core"
  PRERELEASE="$pre"
}

# Prints -1, 0 or 1 depending on how version "$1" compares to version "$2"
# under SemVer 2.0.0 precedence (section 11).
compare_versions() {
  local a="$1" b="$2"
  split_version "$a"
  local a_major=$CORE_MAJOR a_minor=$CORE_MINOR a_patch=$CORE_PATCH a_pre=$PRERELEASE
  split_version "$b"
  local b_major=$CORE_MAJOR b_minor=$CORE_MINOR b_patch=$CORE_PATCH b_pre=$PRERELEASE

  if [ "$((10#$a_major))" -ne "$((10#$b_major))" ]; then
    if [ "$((10#$a_major))" -gt "$((10#$b_major))" ]; then echo 1; else echo -1; fi
    return
  fi
  if [ "$((10#$a_minor))" -ne "$((10#$b_minor))" ]; then
    if [ "$((10#$a_minor))" -gt "$((10#$b_minor))" ]; then echo 1; else echo -1; fi
    return
  fi
  if [ "$((10#$a_patch))" -ne "$((10#$b_patch))" ]; then
    if [ "$((10#$a_patch))" -gt "$((10#$b_patch))" ]; then echo 1; else echo -1; fi
    return
  fi

  if [ -z "$a_pre" ] && [ -z "$b_pre" ]; then
    echo 0
    return
  fi
  if [ -z "$a_pre" ]; then
    # a is a release, b is a pre-release of the same core: a > b.
    echo 1
    return
  fi
  if [ -z "$b_pre" ]; then
    echo -1
    return
  fi

  local -a a_ids b_ids
  IFS='.' read -r -a a_ids <<<"$a_pre"
  IFS='.' read -r -a b_ids <<<"$b_pre"

  local i=0 n=${#a_ids[@]} m=${#b_ids[@]} min=${#a_ids[@]}
  [ "$m" -lt "$min" ] && min=$m

  while [ "$i" -lt "$min" ]; do
    local ai="${a_ids[$i]}" bi="${b_ids[$i]}"
    local a_numeric=0 b_numeric=0
    [[ "$ai" =~ ^[0-9]+$ ]] && a_numeric=1
    [[ "$bi" =~ ^[0-9]+$ ]] && b_numeric=1

    if [ "$a_numeric" -eq 1 ] && [ "$b_numeric" -eq 1 ]; then
      if [ "$((10#$ai))" -ne "$((10#$bi))" ]; then
        if [ "$((10#$ai))" -gt "$((10#$bi))" ]; then echo 1; else echo -1; fi
        return
      fi
    elif [ "$a_numeric" -eq 1 ] && [ "$b_numeric" -eq 0 ]; then
      echo -1
      return
    elif [ "$a_numeric" -eq 0 ] && [ "$b_numeric" -eq 1 ]; then
      echo 1
      return
    else
      if [ "$ai" != "$bi" ]; then
        if [[ "$ai" < "$bi" ]]; then echo -1; else echo 1; fi
        return
      fi
    fi
    i=$((i + 1))
  done

  if [ "$n" -ne "$m" ]; then
    if [ "$n" -gt "$m" ]; then echo 1; else echo -1; fi
    return
  fi

  echo 0
}

PREFIX="${PLUGIN}--v"
BEST_TAG=""
BEST_VERSION=""

while IFS= read -r tag || [ -n "$tag" ]; do
  [ -n "$tag" ] || continue
  case "$tag" in
    "$PREFIX"*) candidate="${tag#"$PREFIX"}" ;;
    *) continue ;;
  esac
  is_strict_semver "$candidate" || continue

  cmp=$(compare_versions "$candidate" "$VERSION")
  [ "$cmp" -lt 0 ] || continue

  if [ -z "$BEST_VERSION" ]; then
    BEST_TAG="$tag"
    BEST_VERSION="$candidate"
  else
    cmp2=$(compare_versions "$candidate" "$BEST_VERSION")
    if [ "$cmp2" -gt 0 ]; then
      BEST_TAG="$tag"
      BEST_VERSION="$candidate"
    fi
  fi
done

if [ -n "$BEST_TAG" ]; then
  printf '%s\n' "$BEST_TAG"
fi
