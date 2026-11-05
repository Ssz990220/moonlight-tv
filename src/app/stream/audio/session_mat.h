#pragma once
#include <stdbool.h>

// One owned, bounded local connection per streaming session.
bool session_mat_prepare(void);
bool session_mat_open(void);
void session_mat_close(void);
