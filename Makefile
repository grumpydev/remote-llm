.PHONY: test test-strict format

test:
	./scripts/test

test-strict:
	./scripts/test --require-tools

format:
	shfmt -w scripts docker/opencode-worker

