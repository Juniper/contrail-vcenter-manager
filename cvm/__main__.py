#!/usr/bin/env python
import argparse
import logging
import sys

import gevent
import yaml

from cvm.container import CVMContainer

gevent.monkey.patch_all()


def load_config(config_file):
    with open(config_file, 'r') as ymlfile:
        return yaml.load(ymlfile)


def main(args):
    cfg = load_config(args.config_file)
    ioc_container = CVMContainer(config=cfg)

    cvm_logger = ioc_container.logger()
    cvm_logger.init_sandesh()
    cvm_logger.configure_logger()

    vmware_monitor = ioc_container.vmware_monitor()
    vmware_monitor.sync()

    greenlets = [
        gevent.spawn(vmware_monitor.start()),
    ]
    gevent.joinall(greenlets)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", action="store", dest="config_file",
                        default='/etc/contrail/contrail-vcenter-manager/config.yaml')
    parsed_args = parser.parse_args()
    try:
        main(parsed_args)
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        logger = logging.getLogger('cvm')
        logger.critical('', exc_info=True)
        raise
