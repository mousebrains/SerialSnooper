# Serial Snooper
Read from one serial port and echo it to another, and vice versa

./Snooper --port0=/dev/tty0 --port1=/dev/tty1

will read from tty0 and send to tty1, and read from tty1 and send to tty0.

There is a test mode, --test, which uses ptys to test the software.
