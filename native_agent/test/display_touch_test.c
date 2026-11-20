#include "../src/display_touch.h"

int main(int argc, char **argv)
{
    return argc == 2 ? c300x_display_touch_cli(argv[1]) : 2;
}
