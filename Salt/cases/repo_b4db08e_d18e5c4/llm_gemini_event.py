# -*- coding: utf-8 -*-
'''
Manage events

Events are all fired off via a zeromq 'pub' socket, and listened to with
local zeromq 'sub' sockets


All of the formatting is self contained in the event module, so
we should be able to modify the structure in the future since the same module
used to read events is the same module used to fire off events.

Old style event messages were comprised of two parts delimited
at the 20 char point. The first 20 characters are used for the zeromq
subscriber to match publications and 20 characters was chosen because it was at
the time a few more characters than the length of a jid (Job ID).
Any tags of length less than 20 characters were padded with "|" chars out to 20 characters.
Although not explicit, the data for an event comprised a python dict that was serialized by
msgpack.

New style event messages support event tags longer than 20 characters while still
being backwards compatible with old style tags.
The longer tags better enable name spaced event tags which tend to be longer.
Moreover, the constraint that the event data be a python dict is now an explicit
constraint and fire-event will now raise a ValueError if not. Tags must be
ascii safe strings, that is, have values less than 0x80

Since the msgpack dict (map) indicators have values greater than or equal to 0x80
it can be unambiguously determined if the start of data is at char 21 or not.

In the new style:
When the tag is longer than 20 characters, an end of tag string
is appended to the tag given by the string constant TAGEND, that is, two line feeds '\n\n'.
When the tag is less than 20 characters then the tag is padded with pipes
"|" out to 20 characters as before.
When the tag is exactly 20 characters no padded is done.

The get_event method intelligently figures out if the tag is longer than 20 characters.


The convention for namespacing is to use dot characters "." as the name space delimiter.
The name space "salt" is reserved by SaltStack for internal events.

For example:
Namespaced tag
    'salt.runner.manage.status.start'

'''

# Import python libs
import os
import fnmatch
import glob
import hashlib
import errno
import logging
import time
import datetime
import multiprocessing
from multiprocessing import Process
from collections import MutableMapping

# Import third party libs
try:
    import zmq
except ImportError:
    # Local mode does not need zmq
    pass
import yaml

# Import salt libs
import salt.payload
import salt.loader
import salt.state
import salt.utils
import salt.utils.cache
from salt._compat import string_types
log = logging.getLogger(__name__)

# The SUB_EVENT set is for functions that require events fired based on
# component executions, like the state system
SUB_EVENT = set([
            'state.highstate',
            'state.sls',
            ])

TAGEND = '\n\n'  # long tag delimiter
TAGPARTER = '/'  # name spaced tag delimiter
SALT = 'salt'  # base prefix for all salt/ events
# dict map of namespaced base tag prefixes for salt events
TAGS = {
    'auth': 'auth',  # prefix for all salt/auth events
    'job': 'job',  # prefix for all salt/job events (minion jobs)
    'key': 'key',  # prefix for all salt/key events
    'minion': 'minion',  # prefix for all salt/minion events (minion sourced events)
    'syndic': 'syndic',  # prefix for all salt/syndic events (syndic minion sourced events)
    'run': 'run',  # prefix for all salt/run events (salt runners)
    'wheel': 'wheel',  # prefix for all salt/wheel events
    'cloud': 'cloud',  # prefix for all salt/cloud events
    'fileserver': 'fileserver',  # prefix for all salt/fileserver events
    'queue': 'queue',  # prefix for all salt/queue events
}


def get_event(node, sock_dir=None, transport='zeromq', opts=None, listen=True):
    '''
    Return an event object suitable for the named transport
    '''
    if transport == 'zeromq':
        if node == 'master':
            return MasterEvent(sock_dir or opts.get('sock_dir', None))
        return SaltEvent(node, sock_dir, opts)
    elif transport == 'raet':
        import salt.utils.raetevent
        return salt.utils.raetevent.SaltEvent(node,
                                              sock_dir=sock_dir,
                                              listen=listen,
                                              opts=opts)


def tagify(suffix='', prefix='', base=SALT):
    '''
    convenience function to build a namespaced event tag string
    from joining with the TABPART character the base, prefix and suffix

    If string prefix is a valid key in TAGS Then use the value of key prefix
    Else use prefix string

    If suffix is a list Then join all string elements of suffix individually
    Else use string suffix

    '''
    parts = [base, TAGS.get(prefix, prefix)]
    if hasattr(suffix, 'append'):  # list so extend parts
        parts.extend(suffix)
    else:  # string so append
        parts.append(suffix)
    return TAGPARTER.join([part for part in parts if part])


class SaltEvent(object):
    '''
    The base class used to manage salt events
    '''
    def __init__(self, node, sock_dir=None, opts=None):
        self.serial = salt.payload.Serial({'serial': 'msgpack'})
        self.context = zmq.Context()
        self.poller = zmq.Poller()
        self.cpub = False
        self.cpush = False
        if opts is None:
            opts = {}
        self.opts = opts
        if sock_dir is None:
            sock_dir = opts.get('sock_dir', None)
        self.puburi, self.pulluri = self.__load_uri(sock_dir, node)
        self.pending_events = []

    def __load_uri(self, sock_dir, node):
        '''
        Return the string URI for the location of the pull and pub sockets to
        use for firing and listening to events
        '''
        hash_type = getattr(hashlib, self.opts.get('hash_type', 'md5'))
        # Only use the first 10 chars to keep longer hashes from exceeding the
        # max socket path length.
        id_hash = hash_type(self.opts.get('id', '')).hexdigest()[:10]
        if node == 'master':
            puburi = 'ipc://{0}'.format(os.path.join(
                    sock_dir,
                    'master_event_pub.ipc'
                    ))
            salt.utils.check_ipc_path_max_len(puburi)
            pulluri = 'ipc://{0}'.format(os.path.join(
                    sock_dir,
                    'master_event_pull.ipc'
                    ))
            salt.utils.check_ipc_path_max_len(pulluri)
        else:
            if self.opts.get('ipc_mode', '') == 'tcp':
                puburi = 'tcp://127.0.0.1:{0}'.format(
                        self.opts.get('tcp_pub_port', 4510)
                        )
                pulluri = 'tcp://127.0.0.1:{0}'.format(
                        self.opts.get('tcp_pull_port', 4511)
                        )
            else:
                puburi = 'ipc://{0}'.format(os.path.join(
                        sock_dir,
                        'minion_event_{0}_pub.ipc'.format(id_hash)
                        ))
                salt.utils.check_ipc_path_max_len(puburi)
                pulluri = 'ipc://{0}'.format(os.path.join(
                        sock_dir,
                        'minion_event_{0}_pull.ipc'.format(id_hash)
                        ))
                salt.utils.check_ipc_path_max_len(pulluri)
        log.debug(
            '{0} PUB socket URI: {1}'.format(self.__class__.__name__, puburi)
        )
        log.debug(
            '{0} PULL socket URI: {1}'.format(self.__class__.__name__, pulluri)
        )
        return puburi, pulluri

    def subscribe(self, tag=None):
        '''
        Subscribe to events matching the passed tag.
        '''
        if not self.cpub:
            self.connect_pub()

    def unsubscribe(self, tag=None):
        '''
        Un-subscribe to events matching the passed tag.
        '''
        return

    def connect_pub(self):
        '''
        Establish the publish connection
        '''
        self.sub = self.context.socket(zmq.SUB)
        self.sub.connect(self.puburi)
        self.poller.register(self.sub, zmq.POLLIN)
        self.sub.setsockopt(zmq.SUBSCRIBE, '')
        self.cpub = True

    def connect_pull(self, timeout=1000):
        '''
        Establish a connection with the event pull socket
        Set the send timeout of the socket options to timeout (in milliseconds)
        Default timeout is 1000 ms
        The linger timeout must be at least as long as this timeout
        '''
        self.push = self.context.socket(zmq.PUSH)
        try:
            # bug in 0MQ default send timeout of -1 (infinite) is not infinite
            self.push.setsockopt(zmq.SNDTIMEO, timeout)
        except AttributeError:
            # This is for ZMQ < 2.2 (Caught when ssh'ing into the Jenkins
            #                        CentOS5, which still uses 2.1.9)
            pass
        self.push.connect(self.pulluri)
        self.cpush = True

    @classmethod
    def unpack(cls, raw, serial=None):
        if serial is None:
            serial = salt.payload.Serial({'serial': 'msgpack'})

        if ord(raw[20]) >= 0x80:  # old style
            mtag = raw[0:20].rstrip('|')
            mdata = raw[20:]
        else:  # new style
            mtag, sep, mdata = raw.partition(TAGEND)  # split tag from data

        data = serial.loads(mdata)
        return mtag, data

    def _check_pending(self, tag, pending_tags):
        """Check the pending_events list for events that match the tag

        :param tag: The tag to search for
        :type tag: str
        :param pending_tags: List of tags to preserve
        :type pending_tags: list[str]
        :return:
        """
        old_events = self.pending_events
        self.pending_events = []
        ret = None
        for evt in old_events:
            if evt['tag'].startswith(tag):
                if ret is None:
                    ret = evt
                else:
                    self.pending_events.append(evt)
            elif any(evt['tag'].startswith(ptag) for ptag in pending_tags):
                self.pending_events.append(evt)
        return ret

    def _get_event(self, wait, tag, pending_tags):
        start = time.time()
        timeout_at = start + wait
        while not wait or time.time() <= timeout_at:
            # convert to milliseconds
            socks = dict(self.poller.poll(wait * 1000))
            if socks.get(self.sub) != zmq.POLLIN:
                continue

            try:
                ret = self.get_event_block()  # Please do not use non-blocking mode here.
                                              # Reliability is more important than pure speed on the event bus.
            except zmq.ZMQError as ex:
                if ex.errno == errno.EAGAIN or ex.errno == errno.EINTR:
                    continue
                else:
                    raise

            if not ret['tag'].startswith(tag):  # tag not match
                if any(ret['tag'].startswith(ptag) for ptag in pending_tags):
                    self.pending_events.append(ret)
                wait = timeout_at - time.time()
                continue

            log.trace('get_event() received = {0}'.format(ret))
            return ret

        return None

    def get_event(self, wait=5, tag='', full=False, use_pending=False, pending_tags=None):
        '''
        Get a single publication.
        IF no publication available THEN block for upto wait seconds
        AND either return publication OR None IF no publication available.

        IF wait is 0 then block forever.

        New in Boron always checks the list of pending events

        use_pending
            Defines whether to keep all unconsumed events in a pending_events