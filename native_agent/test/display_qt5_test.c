/* The --display-qt5 command on its own, as the agent runs it. */
#include "../src/display_qt5.h"

int main(int argc, char **argv)
{
    return c300x_display_qt5_cli(argc - 1, argv + 1);
}
