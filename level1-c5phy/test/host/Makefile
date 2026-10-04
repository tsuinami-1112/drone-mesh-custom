# Desktop tests for the level1-c5phy signal processing: cd test/host && make
CC      ?= gcc
CFLAGS  ?= -std=gnu11 -O2 -Wall -Wextra -Wno-unused-parameter
SRC     = ../../src
OBJS    = $(SRC)/demod.c $(SRC)/bearing.c $(SRC)/report.c $(SRC)/fpv_channels.c

all: test_level1
	./test_level1 > json_samples.txt; st=$$?; cat json_samples.txt; test $$st -eq 0
	python3 check_json.py json_samples.txt

test_level1: test_level1.c $(OBJS) $(SRC)/demod.h $(SRC)/bearing.h $(SRC)/report.h $(SRC)/fpv_channels.h
	$(CC) $(CFLAGS) -I$(SRC) -I../../include -o $@ test_level1.c $(OBJS) -lm

clean:
	rm -f test_level1 json_samples.txt

.PHONY: all clean
