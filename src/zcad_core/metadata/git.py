"""Running git on a directory of our choosing, even from inside a git hook."""

import os

# A git hook exports these for the repository running it, and they override
# where git would otherwise look: with GIT_DIR set, ``git -C <dir>`` and
# ``cwd=<dir>`` still act on the hook's repository, reading it, or, for
# ``init``, ``config``, or ``commit``, writing to it.
REPOSITORY_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        "GIT_PREFIX",
    }
)


def git_environment() -> dict[str, str]:
    """This process's environment without the variables that point git at a
    repository, so git finds the repository from the directory it is given."""

    return {
        name: value
        for name, value in os.environ.items()
        if name not in REPOSITORY_VARIABLES
    }
