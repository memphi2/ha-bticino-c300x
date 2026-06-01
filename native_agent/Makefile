CC ?= gcc
PYTHON ?= python3
ARMHF_CC ?= arm-linux-gnueabihf-gcc
ARMHF_READELF ?= arm-linux-gnueabihf-readelf
C300X_DEVICE_SYSROOT ?=
AGENT_VERSION ?= $(shell tr -d '[:space:]' < VERSION)
BUILD_DIR := build
HOST_BUILD_DIR := $(BUILD_DIR)/host
ARMHF_BUILD_DIR := $(BUILD_DIR)/armhf
TARGET := $(HOST_BUILD_DIR)/c300x-agent-native
ARMHF_TARGET := $(ARMHF_BUILD_DIR)/c300x-agent-native
SOURCES := $(wildcard src/*.c)
HEADERS := $(wildcard src/*.h)
OBJECTS := $(patsubst src/%.c,$(HOST_BUILD_DIR)/%.o,$(SOURCES))
ARMHF_OBJECTS := $(patsubst src/%.c,$(ARMHF_BUILD_DIR)/%.o,$(SOURCES))
ARMHF_OBJECTS += $(ARMHF_BUILD_DIR)/arm_start.o
STACK_USAGE_LIMIT ?= 24576

CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Werror -pedantic -D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L -DC300X_NATIVE_AGENT_VERSION=\"$(AGENT_VERSION)\"
LDFLAGS ?= -pthread
ARMHF_CFLAGS ?= $(CFLAGS) -D_TIME_BITS=32
ifeq ($(STACK_USAGE),1)
ARMHF_CFLAGS += -fstack-usage
endif
ifneq ($(C300X_DEVICE_SYSROOT),)
ARMHF_PTHREAD_LDFLAGS := -Wl,-rpath-link,$(C300X_DEVICE_SYSROOT)/lib -L$(C300X_DEVICE_SYSROOT)/lib -l:libpthread.so.0 -l:libc.so.6 -l:ld-linux-armhf.so.3
else
ARMHF_PTHREAD_LDFLAGS := -Wl,--no-as-needed -l:libpthread.so.0
endif
ARMHF_LDFLAGS ?= $(LDFLAGS) $(ARMHF_PTHREAD_LDFLAGS) -nostartfiles

.PHONY: all armhf armhf-abi-check armhf-stack-check check smoke clean

all: $(TARGET)

armhf: $(ARMHF_TARGET)

armhf-abi-check: $(ARMHF_TARGET)
	@$(ARMHF_READELF) --version-info $(ARMHF_TARGET) | grep -E 'GLIBC_2\.([3-9][0-9]|2[7-9])' >/dev/null && { \
		echo "FAIL: $(ARMHF_TARGET) requires glibc newer than the C300X firmware glibc 2.26"; \
		$(ARMHF_READELF) --version-info $(ARMHF_TARGET) | grep -E 'GLIBC_2\.([3-9][0-9]|2[7-9])'; \
		exit 1; \
	} || echo "ARMHF ABI check passed"

armhf-stack-check:
	$(MAKE) clean
	$(MAKE) armhf STACK_USAGE=1
	$(PYTHON) ../scripts/check_stack_usage.py $(ARMHF_BUILD_DIR) --limit $(STACK_USAGE_LIMIT)

$(TARGET): $(OBJECTS)
	$(CC) $(CFLAGS) -o $@ $(OBJECTS) $(LDFLAGS)

$(ARMHF_TARGET): $(ARMHF_OBJECTS)
	$(ARMHF_CC) $(ARMHF_CFLAGS) -o $@ $(ARMHF_OBJECTS) $(ARMHF_LDFLAGS)

$(HOST_BUILD_DIR)/%.o: src/%.c $(HEADERS) | $(HOST_BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(ARMHF_BUILD_DIR)/%.o: src/%.c $(HEADERS) | $(ARMHF_BUILD_DIR)
	$(ARMHF_CC) $(ARMHF_CFLAGS) -c $< -o $@

$(ARMHF_BUILD_DIR)/arm_start.o: src/arm_start.S | $(ARMHF_BUILD_DIR)
	$(ARMHF_CC) $(ARMHF_CFLAGS) -c $< -o $@

$(HOST_BUILD_DIR) $(ARMHF_BUILD_DIR):
	mkdir -p $@

check: $(TARGET)
	$(TARGET) --config config.example.json --check-config

smoke: $(TARGET)
	$(PYTHON) test/smoke.py $(TARGET)

clean:
	rm -rf $(BUILD_DIR)
