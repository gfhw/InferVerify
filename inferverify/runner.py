"""Run Robot Framework suites programmatically via the official ``robot.run`` API.

The thresholds declared in the CR are passed into the suites as Robot variables
so the assertions stay declarative: users change ``spec.thresholds`` without
editing any test code.
"""

import os

from robot import run

from .listener import ProgressListener


def run_suites(suites, variables, report_dir, on_progress=None):
    """Run the given Robot suites and return ``(return_code, listener)``.

    ``variables`` is a list of "NAME:value" strings (Robot's --variable syntax).
    """
    os.makedirs(report_dir, exist_ok=True)

    listener = ProgressListener(on_progress=on_progress)

    rc = run(
        *suites,
        outputdir=report_dir,
        listener=listener,
        variable=variables,
        # Keep operator stdout clean; the structured results come from listener.
        console=None,
        log="log.html",
        report="report.html",
        output="output.xml",
    )

    return rc, listener
