#!/usr/bin/env python
###############################################################################
# IBM(c) 2018 EPL license http://www.eclipse.org/legal/epl-v10.html
###############################################################################
# -*- coding: utf-8 -*-
#
from __future__ import print_function
import gevent
import time

from common.task import ParallelNodesCommand
from common.exceptions import SelfClientException, SelfServerException
from hwctl import openbmc_client as openbmc

import logging
logger = logging.getLogger('xcatagent')


POWER_STATE_DB = {
    "on"      : "powering-on",
    "off"     : "powering-off",
    "softoff" : "powering-off",
    "boot"    : "powering-on",
    "reset"   : "powering-on",
}
class OpenBMCPowerTask(ParallelNodesCommand):
    """Executor for power-related actions."""

    def _determine_state(self, states):

        chassis_state = states.get('chassis')
        host_state = states.get('host')
        state = 'Unknown'
        if chassis_state == 'Off':
            state = chassis_state

        elif chassis_state == 'On':
            if host_state == 'Off':
                state = 'chassison'
            elif host_state in ['Quiesced', 'Running']:
                state = host_state
            else:
                state = 'Unexpected host state=%s' % host_state
        else:
            state = 'Unexpected chassis state=%s' % chassis_state
        return state

    def get_state(self, **kw):

        node = kw['node']
        obmc = openbmc.OpenBMCRest(name=node, nodeinfo=kw['nodeinfo'], messager=self.callback,
                                   debugmode=self.debugmode, verbose=self.verbose)
        state = 'Unknown'
        try:
            obmc.login()
            states = obmc.list_power_states()
            state = self._determine_state(states)
            self.callback.info('%s: %s' % (node, openbmc.RPOWER_STATES.get(state, state)))

        except (SelfServerException, SelfClientException) as e:
            self.callback.error(e.message, node)

        return state

    def get_bmcstate(self, **kw):

        node = kw['node']
        obmc = openbmc.OpenBMCRest(name=node, nodeinfo=kw['nodeinfo'], messager=self.callback,
                                   debugmode=self.debugmode, verbose=self.verbose)
        bmc_not_ready = bmc_state = 'NotReady'
        try:
            obmc.login()
        except SelfServerException as e:
            # Special exception handling for login failure
            login_message = "Login to BMC failed: Can't connect to {0} {1}.".format(e.host_and_port, e.detail_msg)
            self.callback.error(login_message, node)
            return bmc_state

        try:
            state = obmc.get_bmc_state()
            bmc_state = state.get('bmc')

            if bmc_state != 'Ready':
                bmc_state = bmc_not_ready

            self.callback.info('%s: %s' % (node, openbmc.RPOWER_STATES.get(bmc_state, bmc_state)))

        except SelfServerException, SelfClientException:
            # There is no response when BMC is not ready
            self.callback.error(openbmc.RPOWER_STATES[bmc_not_ready], node)

        return bmc_state

    def set_state(self, state, **kw):

        node = kw['node']
        obmc = openbmc.OpenBMCRest(name=node, nodeinfo=kw['nodeinfo'], messager=self.callback,
                                   debugmode=self.debugmode, verbose=self.verbose)
        try:
            obmc.login()
            ret = obmc.set_power_state(state)
            new_status = POWER_STATE_DB.get(state, '')

            self.callback.info('%s: %s' % (node, state))
            if new_status:
                self.callback.update_node_attributes('status', node, new_status)
        except (SelfServerException, SelfClientException) as e:
            self.callback.error(e.message, node)

    def reboot(self, optype='boot', **kw):

        node = kw['node']
        obmc = openbmc.OpenBMCRest(name=node, nodeinfo=kw['nodeinfo'], messager=self.callback,
                                   debugmode=self.debugmode, verbose=self.verbose)
        try:
            obmc.login()
            states = obmc.list_power_states()
            status = self._determine_state(states)

            new_status =''
            if optype == 'reset' and status in ['Off', 'chassison']:
                status = openbmc.RPOWER_STATES['Off']
                self.callback.info('%s: %s'  % (node, status))
            else:
                if status not in ['Off', 'off']:
                    obmc.set_power_state('off')
                    self.callback.update_node_attributes('status', node, POWER_STATE_DB['off'])

                    off_flag = False
                    start_timeStamp = int(time.time())
                    for i in range (0, 30):
                        states = obmc.list_power_states()
                        status = self._determine_state(states)
                        if openbmc.RPOWER_STATES.get(status) == 'off':
                            off_flag = True
                            break
                        gevent.sleep( 2 )

                    end_timeStamp = int(time.time())

                    if not off_flag:
                        error = 'Error: Sent power-off command but state did not change ' \
                                 'to off after waiting %s seconds. (State= %s).' % (end_timeStamp - start_timeStamp, status)
                        raise SelfServerException(error)

                ret = obmc.set_power_state('on')
                self.callback.update_node_attributes('status', node, POWER_STATE_DB['on'])

                self.callback.info('%s: %s'  % (node, 'reset'))

        except (SelfServerException, SelfClientException) as e:
            self.callback.error(e.message, node)

    def reboot_bmc(self, optype='warm', **kw):

        node = kw['node']
        obmc = openbmc.OpenBMCRest(name=node, nodeinfo=kw['nodeinfo'], messager=self.callback,
                                   debugmode=self.debugmode, verbose=self.verbose)
        new_status = ''
        try:
            obmc.login()
        except (SelfServerException, SelfClientException) as e:
            self.callback.error(e.message, node)
        else:
            try:
                obmc.reboot_bmc(optype)
            except (SelfServerException, SelfClientException) as e:
                self.callback.error(e.message, node)
            else:
                self.callback.info('%s: %s' % (node, openbmc.RPOWER_STATES['bmcreboot']))

