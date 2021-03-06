#!/usr/bin/env python3

import datetime
import os
import signal
import subprocess
import sys
import time

from configparser import ConfigParser

class NetMan(object):
  IF_UP_CMD = 'ip link set "{iface}" up'
  SCAN_CMD = 'iw "{iface}" scan | grep SSID'
  IW_CONNECT_CMD = 'iw {iface} connect "{ssid}"'
  WPA_CONFIG_CMD = 'wpa_passphrase "{ssid}" "{password}" > "/etc/sysconfig/wpa-{ssid}.conf"'
  WPA_CONNECT_CMD = 'wpa_supplicant -B -Dnl80211 -i"{iface}" -c"{config}"'
  DHCP_CMD = "dhcpcd -4 -L {iface}"
  IP_ADD_CMD = "ip addr add {ip} dev {iface}"
  IP_RM_CMD = "ip addr del {ip} dev {iface}"
  ROUTE_ADD_CMD = "ip route add default via {gateway} dev {iface}"

  interface = "wlan0"

  def __init__(self):
    self.config_map = ConfigParser()
    self.read_config()
    self.reset_state()

  def read_config(self):
    self.config_map.read(os.path.join(os.path.dirname(__file__), "config"))
    self.SSIDS = self.config_map.sections()

  def reset_state(self):
    self.encrypted = False
    self.connected = None
    self.manual_ip = False
    self.find_better()

  def get_visible_ssids(self):
    os.system(self.IF_UP_CMD.format(iface=self.interface))
    try:
      scan_out = subprocess.check_output(self.SCAN_CMD.format(iface=self.interface), shell=True).decode('utf-8')
    except subprocess.CalledProcessError:
      return None

    ssids = []
    for line in scan_out.split(os.linesep):
      splt = line.strip().split("SSID: ")
      if len(splt) > 1:
        ssids.append(splt[1].strip())

    return ssids

  def make_wpa_config(self, ssid, password):
    os.system(self.WPA_CONFIG_CMD.format(ssid=ssid, password=password))

  def find_better(self):
    if self.connected is None:
      self.better = self.SSIDS
    else:
      self.better = self.SSIDS[:self.SSIDS.index(self.connected)]

  def connect(self, name):
    print("Trying to connect to %s..." % name)
    if self.connected is not None:
      self.network_off()

    if 'pass' in self.config_map[name]:
      self.connect_encrypted(name)
    else:
      self.connect_open(name)

    self.manual_ip = 'ip' in self.config_map[name]
    if self.manual_ip:
      self.ip_addr = self.config_map[name]['ip']
      os.system(self.IP_ADD_CMD.format(ip=self.ip_addr, iface=self.interface))
      if 'gateway' in self.config_map[name]:
        os.system(self.ROUTE_ADD_CMD.format(gateway=self.config_map[name]['gateway'], iface=self.interface))
    else:
      os.system(self.DHCP_CMD.format(iface=self.interface))

    self.connected = name
    self.find_better()
    print("Connected to %s." % name)

  def connect_encrypted(self, name):
    config = "/etc/sysconfig/wpa-%s.conf" % name
    if not os.path.exists(config):
      self.make_wpa_config(name, self.config_map[name]['pass'])

    os.system(self.WPA_CONNECT_CMD.format(iface=self.interface, config=config))
    self.encrypted = True

  def connect_open(self, name):
    os.system(self.IW_CONNECT_CMD.format(iface=self.interface, ssid=name))

  def network_off(self):
    print("Killing network.")
    if self.encrypted:
      os.system("pkill -f wpa_supplicant")
      self.encrypted = False
    else:
      os.system("iw %s disconnect" % self.interface)

    if self.manual_ip:
      os.system(self.IP_RM_CMD.format(ip=self.ip_addr, iface=self.interface))

    os.system("pkill -f dhcpcd")
    self.reset_state()

  def assert_dhcp(self):
    if subprocess.call("pgrep -f dhcpcd", shell=True, stdout=subprocess.PIPE):
      os.system(self.DHCP_CMD.format(iface=self.interface))

  def run(self):
    print("Running NetMan at %s" % str(datetime.datetime.now()))
    while 1:
      print("scanning...")
      visible_ssids = self.get_visible_ssids()

      if visible_ssids is None:
        time.sleep(0.2)
        continue

      if self.connected not in visible_ssids:
        candidates = self.SSIDS
      else:
        candidates = self.better

      for ssid in candidates:
        if ssid in visible_ssids:
          self.connect(ssid)
          break

      if self.connected and not self.encrypted:
        # This is in case of the dreaded "Calling CRDA to update world
        # regulatory domain" event which disassociates from the AP.
        # TODO Only run this if we are disconnected.
        self.connect_open(self.connected)

      if not self.manual_ip:
        self.assert_dhcp()

      time.sleep(5)
      self.read_config()
      self.find_better()

  def cleanup(self):
    self.network_off()
    sys.exit(0)

if __name__ == "__main__":
  netman = NetMan()

  signals = [signal.SIGINT, signal.SIGTERM]
  [signal.signal(s, lambda x, y: netman.cleanup()) for s in signals]

  netman.run()
