#include <notify.h>
#include <stdio.h>
int main(int c, char **v) { int r = notify_post(c > 1 ? v[1] : "homescreen.import"); printf("posted %d\n", r); return r; }
