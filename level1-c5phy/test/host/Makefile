# Desktop tests for the level1-c5phy signal processing: cd test/host && make
# The suite runs twice: with the default plan (5.8 GHz only, L4..L8) and as the
# dual-band build with the full Lowband (-DDUAL_BAND=1 -DLOWBAND=2).
CC      ?= gcc
CFLAGS  ?= -std=gnu11 -O2 -Wall -Wextra -Wno-unused-parameter
SRC     = ../../src
OBJS    = $(SRC)/demod.c $(SRC)/bearing.c $(SRC)/report.c $(SRC)/fpv_channels.c $(SRC)/switch_bits.c $(SRC)/sweep_decide.c
HDRS    = $(SRC)/demod.h $(SRC)/bearing.h $(SRC)/report.h $(SRC)/fpv_channels.h $(SRC)/switch_bits.h $(SRC)/sweep_decide.h
DUAL_FLAGS = -DDUAL_BAND=1 -DLOWBAND=2

all: test_level1 test_level1_dualband
	./test_level1 > json_samples.txt; st=$$?; cat json_samples.txt; test $$st -eq 0
	python3 check_json.py json_samples.txt
	./test_level1_dualband > json_samples_dualband.txt; st=$$?; cat json_samples_dualband.txt; test $$st -eq 0
	python3 check_json.py json_samples_dualband.txt

test_level1: test_level1.c $(OBJS) $(HDRS)
	$(CC) $(CFLAGS) -I$(SRC) -I../../include -o $@ test_level1.c $(OBJS) -lm

test_level1_dualband: test_level1.c $(OBJS) $(HDRS)
	$(CC) $(CFLAGS) $(DUAL_FLAGS) -I$(SRC) -I../../include -o $@ test_level1.c $(OBJS) -lm

clean:
	rm -f test_level1 test_level1_dualband json_samples.txt json_samples_dualband.txt

.PHONY: all clean
