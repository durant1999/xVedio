.PHONY: test compile

compile:
	python -m compileall video_understanding tests

test:
	python -m unittest discover -s tests

