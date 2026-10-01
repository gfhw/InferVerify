"""InferVerify operator entrypoint.

Run with::

    kopf run -m operator.main --all-namespaces

Importing ``handler`` registers the kopf handlers; kopf then drives the
reconciliation loop.
"""

import kopf

from . import handler  # noqa: F401  # registers handlers


def main():
    kopf.run()


if __name__ == "__main__":
    main()
