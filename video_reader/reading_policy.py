"""Shared behavioral contract for MCP and generated host skills."""
READING_POLICY = (
    'Answer as soon as the inspected evidence is sufficient for the user\'s task. '
    'Investigate uncertainties that could change the answer; retain a continuation path for uninspected material. '
    'Whole-transcript proofreading and full delivery are not prerequisites for every answer. '
    'Preserve raw sources, timestamps, evidence and revisions; never claim full review or observation without it. '
    'Default reading reuses cached OCR and defers new deep checks; request temporal=True or verify=True when the question needs them.'
)
