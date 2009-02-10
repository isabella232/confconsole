# Copyright (c) 2008 Alon Swartz <alon@turnkeylinux.org> - all rights reserved

import os
import re
import time
import fcntl
import struct
import socket

import executil
import conffiles

SIOCGIFADDR = 0x8915
SIOCGIFNETMASK = 0x891b
SIOCGIFBRDADDR = 0x8919

class Error(Exception):
    pass

class Netconf():
    """enumerate network related configurations"""

    class ATTRIBS:
        ADDRS = {
            'addr':         SIOCGIFADDR,
            'netmask':      SIOCGIFNETMASK,
            'brdaddr':      SIOCGIFBRDADDR,
        }

    def __init__(self, ifname):
        self.ifname = ifname
        self.ifreq = (self.ifname + '\0'*32)[:32]

    def _get_addr(self, attrname):
        try:
            sockfd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            result = fcntl.ioctl(sockfd.fileno(), attrname, self.ifreq)
        except IOError:
            return None

        return socket.inet_ntoa(result[20:24])

    def get_gateway(self):
        try:
            output = executil.getoutput("route -n")
        except executil.ExecError:
            return None

        for line in output.splitlines():
            m = re.search('^0.0.0.0\s+(.*?)\s+(.*)\s+%s' % self.ifname, line, re.M)
            if m:
                return m.group(1)

        return None

    def get_nameserver(self):
        def _parse_resolv(path):
            for line in file(path).readlines():
                if line.startswith('nameserver'):
                    return line.strip().split()[1]
            return None

        #/etc/network/interfaces (static)
        interfaces = conffiles.Interfaces()
        for line in interfaces.conf[self.ifname].splitlines():
            line = line.strip()
            if line.startswith('dns-nameservers'):
                return line.split()[1]

        #resolvconf (dhcp)
        path = '/etc/resolvconf/run/interface'
        if os.path.exists(path):
            for f in os.listdir(path):
                if not f.startswith(self.ifname) or f.endswith('.inet'):
                    continue

                nameserver = _parse_resolv(os.path.join(path, f))
                if nameserver:
                    return nameserver

        #/etc/resolv.conf (fallback)
        nameserver = _parse_resolv('/etc/resolv.conf')
        if nameserver:
            return nameserver

        return None

    def __getattr__(self, attrname):
        if attrname in self.ATTRIBS.ADDRS:
            return self._get_addr(self.ATTRIBS.ADDRS[attrname])

        if attrname == "gateway":
            return self.get_gateway()

        if attrname == "nameserver":
            return self.get_nameserver()

class Connection:
    """class for holding a network connections configuration"""

    def __init__(self, proto, attribs, debug=False):
        """
        proto is one of tcp, tcp6, udp
        attribs is a line from /proc/net/$proto (split into an array) 
        """
        self.proto = proto
        self.lhost, self.lport = self._map_hostport(attribs[1])
        self.rhost, self.rport = self._map_hostport(attribs[2])

        self.status = self._map_status(attribs[3])

        if debug:
            print "%s\t%s:%s\t\t%s:%s\t\t%s" % (self.proto, self.lhost, self.lport,
                                                self.rhost, self.rport, self.status)

    @staticmethod
    def _int2host(host):
        return ".".join(map(str, ((host >> 0) & 0xff, (host >> 8) & 0xff,
                                  (host >> 16) & 0xff, (host >> 24) & 0xff)))

    @classmethod
    def _map_hostport(cls, attrib):
        host, port = attrib.split(":", 1)
        host = cls._int2host(int(host, 16))
        port = int(port, 16)

        return host, port

    @staticmethod
    def _map_status(attrib):
        status = {'01': 'ESTABLISHED',
                  '0A': 'LISTENING',
                  '10': 'WAITING'}
        try:
            return status[attrib]
        except KeyError:
            return 'UNKNOWN'


def is_ipaddr(ip):
    ipv4 = '^(25[0-5]|2[0-4]\d|[0-1]?\d?\d)(\.(25[0-5]|2[0-4]\d|[0-1]?\d?\d)){3}$'
    if not re.match(ipv4, ip):
        return False

    try:
        packed = socket.inet_aton(ip)
    except socket.error:
        return False

    return True

def ifup(ifname):
    return executil.getoutput("ifup", ifname)

def ifdown(ifname):
    return executil.getoutput("ifdown", ifname)

def unconfigure_if(ifname):
    try:
        ifdown(ifname)
        interfaces = conffiles.Interfaces()
        interfaces.set_manual(ifname)
        executil.system("ifconfig %s 0.0.0.0" % ifname)
        ifup(ifname)
    except Exception, e:
        return str(e)

def set_static(ifname, addr, netmask, gateway, nameserver):
    try:
        ifdown(ifname)
        interfaces = conffiles.Interfaces()
        interfaces.set_static(ifname, addr, netmask, gateway, nameserver)
        ifup(ifname)
    except Exception, e:
        return str(e)

def set_dhcp(ifname):
    try:
        ifdown(ifname)
        interfaces = conffiles.Interfaces()
        interfaces.set_dhcp(ifname)
        output = ifup(ifname)

        net = Netconf(ifname)
        if not net.addr:
            raise Error('Error obtaining IP address\n\n%s' % output)

    except Exception, e:
        return str(e)

def get_ipconf(ifname):
    net = Netconf(ifname)
    return net.addr, net.netmask, net.gateway, net.nameserver

def get_ifmethod(ifname):
    conf = conffiles.Interfaces().conf
    if not conf.has_key(ifname):
        return None

    m = re.match(".*\niface %s inet (.*)" % ifname, conf[ifname])
    if m:
        return m.group(1)

    return None

def get_ifnames():
    """ returns list of interface names (up and down) """
    ifnames = []
    for line in file('/proc/net/dev').readlines():
        try:
            ifname, junk = line.strip().split(":")
            ifnames.append(ifname)
        except ValueError:
            pass

    return ifnames

def get_hostname():
    return socket.gethostname()

def get_connections():
    connections = []
    for proto in ('tcp', 'tcp6', 'udp'):
        for line in file('/proc/net/' + proto).readlines()[1:]:
            conn = Connection(proto, line.split())
            connections.append(conn)

    return connections


