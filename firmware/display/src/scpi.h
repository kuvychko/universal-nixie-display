// SCPI-style command interpreter for the host interface (docs/host_interface.md), following
// nanovolt-divider's parser: one program message per line, ';' between commands, headers in long
// or short form, case-insensitive, leading ':' optional. Query responses in one line are joined
// with ';' and end with '\n'. Errors go to the queue (SYST:ERR?), never to the response stream.
// SPDX-License-Identifier: MIT
#pragma once
#include <Print.h>

namespace scpi {

void execute(const char *line, Print &out);
void pushError(int code, const char *text);

} // namespace scpi
