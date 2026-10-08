# Waveform models behind some of config.h's numbers; not part of the test suite.
#   make            builds and runs sim_skirt (FM video through a modelled channel-filter skirt)
CC     ?= gcc
CFLAGS ?= -std=gnu11 -O2 -Wall -Wno-unused-function
SRC     = ../../src

all: sim_skirt
	./sim_skirt

sim_skirt: sim_skirt.c $(SRC)/demod.c $(SRC)/demod.h
	$(CC) $(CFLAGS) -I$(SRC) -I../../include -o $@ sim_skirt.c $(SRC)/demod.c -lm

clean:
	rm -f sim_skirt

.PHONY: all clean
