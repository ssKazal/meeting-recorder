# What does this change?

<!-- A short description, and the issue it closes (e.g. "Closes #12"). -->

## Why?

<!-- The problem this solves. -->

## How was it verified?

<!--
Tests alone aren't enough for recording/detection changes — please say what you
actually observed. For example: "recorded a 30s Meet call, paused 10s, saved file
is 20s and both voices are level".
-->

- [ ] `python3 tests/run_tests.py` passes
- [ ] Verified by actually running it (for behaviour changes)

## Checklist

- [ ] Follows the existing style; new logic is in testable pure functions where practical
- [ ] `README.md` / `CHANGELOG.md` updated if behaviour changed
- [ ] No audio filters were added to the **live capture** path (see [CONTRIBUTING](../CONTRIBUTING.md#architecture--read-this-before-changing-the-recorder))
