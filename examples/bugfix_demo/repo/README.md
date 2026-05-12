# Bugfix Demo Fixture

This tiny repository intentionally contains one failing unittest. A real
HarnessCoder model run should inspect the failure, edit `math_utils.py`, rerun
`python -m unittest discover`, and finish after the tests pass.
