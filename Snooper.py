#! /usr/bin/env python3
#
# Listen on two real serial ports.
# Forward all characters from one serial port to the other.
#
# Jan-2020, Pat Welch, pat@mousebrains.com

import serial
import threading
import logging
import queue
import argparse
import pty
import time
import select
import logging
import logging.handlers

def loggerArgs(parser: argparse.ArgumentParser) -> None:
    """ Add my options to an argparse object """
    grp = parser.add_argument_group(description="Log related options")
    grp.add_argument("--logfile", type=str, metavar="filename", help="Log filename")
    grp.add_argument("--verbose", action="store_true", help="Enable debug messages")
    grp.add_argument("--maxlogsize", type=int, default=10000000, metavar="bytes",
            help="Maximum logfile size")
    grp.add_argument("--backupcount", type=int, default=7, metavar="count",
            help="Number of logfiles to keep")

def mkLogger(args:argparse.ArgumentParser, name:str, fmt:str=None) -> logging.Logger:
    """ Make a logging object based on the options in args """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if args.logfile is None:
        ch = logging.StreamHandler()
    else:
        ch = logging.handlers.RotatingFileHandler(args.logfile,
                                maxBytes=args.maxlogsize,
                                backupCount=args.backupcount)

    ch.setLevel(logging.DEBUG if args.verbose else logging.INFO)

    if fmt is None:
        fmt = "%(asctime)s: %(threadName)s:%(levelname)s - %(message)s"
    formatter = logging.Formatter(fmt)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger

class MyThread(threading.Thread):
    def __init__(self, name:str, logger:logging.Logger, err:queue.Queue) -> None:
        threading.Thread.__init__(self, daemon=True)
        self.name = name
        self.logger = logger
        self.err = err

    def run(self) -> None: # Called on start
        try:
            self.runit()
        except Exception as e:
            self.err.put(e)
            self.logger.exception("Unexpected exception")

class Snooper(MyThread):
    def __init__(self, port0:str, port1:str, baud:int,
            logger:logging.Logger, err:queue.Queue) -> None:
        MyThread.__init__(self, "Snooper", logger, err)
        self.port0 = port0
        self.port1 = port1
        self.baud = baud

    def runit(self): # Called on start
        port0 = self.port0
        port1 = self.port1
        logger = self.logger
        logger.info("Starting port0=%s port1=%s baud=%s", port0, port1, self.baud)
        with serial.Serial(port=port0, baudrate=self.baud, timeout=0) as s0:
            with serial.Serial(port=port1, baudrate=self.baud, timeout=0) as s1:
                self.__doit(s0, s1)

    def __doit(self, s0:serial.Serial, s1:serial.Serial) -> None:
        logger = self.logger
        buffer0 = bytearray()
        buffer1 = bytearray()
        logger.info("s0 %s", s0)
        logger.info("s1 %s", s1)
        while True:
            wlist = []
            if len(buffer0): wlist.append(s0)
            if len(buffer1): wlist.append(s1)
            (rlist, wlist, xlist) = select.select([s0, s1], wlist, [])
            for s in rlist:
                c = s.read(8192)
                if len(c) == 0: continue
                if s == s0:
                    buffer1 += c
                    logger.info("%s %s Read %s", s.name, len(buffer1), c)
                else:
                    buffer0 += c
                    logger.info("%s %s Read %s", s.name, len(buffer0), c)
            for s in wlist:
                if s == s0:
                    n = s.write(buffer0)
                    buffer0 = buffer0[n:]
                else:
                    n = s.write(buffer1)
                    buffer1 = buffer1[n:]
                logger.info("%s wrote %d", s.name, n)

class Simulation(MyThread):
    def __init__(self, key:str, delay:int, logger:logging.Logger, err:queue.Queue) -> tuple:
        MyThread.__init__(self, "Sim" + key, logger, err)
        self.key = key
        self.delay = delay
        (self.master, self.slave) = pty.openpty() # pty pair
        self.ttyname = os.ttyname(self.slave)

    def runit(self) -> None: # Called on start
        s = self.master
        msg = "Message from " + self.key + " at {}\r"
        logger = self.logger
        dt = self.delay
        logger.info("Starting %s delay=%s", self.ttyname, dt)
        tNext = time.time() + dt
        while True:
            (rlist, wlist, xlist) = select.select([s], [], [], tNext - time.time())
            if rlist == []: # A Timeout
                a = bytes(msg.format(time.time()), "utf-8")
                logger.info("%s Sending %s", self.ttyname, a)
                os.write(s, a)
                tNext = time.time() + dt
            else:
                c = os.read(s, 1)
                logger.info("%s Recv %s", self.ttyname, c)

if __name__ == "__main__":
    import os.path
    
    parser = argparse.ArgumentParser()
    grp = parser.add_argument_group(description="Serial port options")
    grp.add_argument("--port0", type=str, metavar="devName",
        help="Serial port device name to open")
    grp.add_argument("--port1", type=str, metavar="devName",
        help="Serial port device name to open")
    grp.add_argument("--baud", metavar="baud", default=9600,
        choices=[1200, 2400, 4800, 9600, 19200, 115200],
        help="Serial port baudrate")
    grp = parser.add_argument_group(description="Testing options")
    grp.add_argument("--test", action="store_true", help="Run in test mode using PTYs")
    grp.add_argument("--delay0", type=int, default=11, metavar="seconds",
        help="Delay between messages")
    grp.add_argument("--delay1", type=int, default=17, metavar="seconds",
        help="Delay between messages")
    loggerArgs(parser)
    args = parser.parse_args()

    logger = mkLogger(args, __name__)

    errQueue = queue.Queue()

    threads = []

    if not args.test:
        if args.port0 is None:
            parser.error("--port0 is required unless --test is given")
        if args.port1 is None:
            parser.error("--port1 is required unless --test is given")
        if not os.path.exists(args.port0):
            parser.error("--port0 {} does not exist".format(args.port0))
        if not os.path.exists(args.port1):
            parser.error("--port1 {} does not exist".format(args.port1))
    elif (args.port0 is not None) or (args.port1 is not None):
        parser.error("--port0 and --port1 can not be specified with --test")
    else: # --test
        threads.append(Simulation("0", args.delay0, logger, errQueue))
        threads.append(Simulation("1", args.delay1, logger, errQueue))
        args.port0 = threads[0].ttyname
        args.port1 = threads[1].ttyname

    threads.append(Snooper(args.port0, args.port1, args.baud, logger, errQueue))

    for thr in threads:
        thr.start()

    e = errQueue.get()
    raise(e)
