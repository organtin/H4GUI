#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pygtk
pygtk.require('2.0')
import gtk
import gobject
import pygst
import gst
import datetime
import time
import urllib
import webkit
from subprocess import *
from zmq import *
from h4dbclasses import *
from h4helperclasses import *
from collections import OrderedDict
import h4guiconfig

class H4GtkGui:

    configure = h4guiconfig.configure

    def __init__(self):

        self.configure()

        self.gui_out_messages={
            'startrun': 'GUI_STARTRUN',
            'pauserun': 'GUI_PAUSERUN',
            'restartrun': 'GUI_RESTARTRUN',
            'stoprun': 'GUI_STOPRUN',
            'die': 'GUI_DIE',
            'reconfig': 'GUI_RECONFIG'
            }
        self.gui_in_messages={
            'status': 'STATUS',
            'log': 'GUI_LOG',
            'error': 'GUI_ERROR',
            'sps': 'GUI_SPS',
            'tablepos': 'TAB_IS',
            'tablemoving': 'TAB_MOVING',
            'tabledone': 'TAB_DONE',
            'transfer': 'TRANSFER',
            'spillduration': 'SPILLDURATION'
            }
        self.rsdict={ #imported from H4DAQ/interface/Command.hpp 
            0:'START',
            1:'INIT',
            2:'INITIALIZED',
            3:'BEGINSPILL',
            4:'CLEARED',
            5:'WAITFORREADY',
            6:'CLEARBUSY',
            7:'WAITTRIG',
            8:'READ',
            9:'ENDSPILL',
            10:'RECVBUFFER',
            11:'SENTBUFFER',
            12:'SPILLCOMPLETED',
            13:'BYE',
            14:'ERROR'
            }
        self.remotestatus_juststarted=0
        self.remotestatus_betweenruns=2
        self.remotestatus_betweenspills=3
        self.remotestatus_endofspill=9
        self.remotestatuses_datataking=[6,7,8]
        self.remotestatuses_running=[4,5,6,7,8,9,10,11,12]
        self.remotestatuses_stopped=[0,1,2,13,14]

        self.globalstopconsent=False
        self.wanttostop=False
        self.wanttopause=False

        self.status={
            'localstatus': 'STARTED',
            'runnumber': 0,
            'spillnumber': 0,
            'evinrun': 0,
            'evinspill': 0,
            'table_status': (0,0,'TAB_DONE'),
            'eventsmerged': 0,
            'badspills': 0,
            'spillsize': 0,
            'transferRate': 0,
            'spillduration': 0,
            'trigrate': 0,
            'temperatures': [],
            'humidity': 0,
            'dewpoint': 0,
            'laudatemp': 0
            }

        self.remote={}
        for node,addr in self.nodes:
            self.remote[('statuscode',node)]=self.remotestatus_juststarted
            self.remote[('status',node)]=self.rsdict[self.remote[('statuscode',node)]]
            self.remote[('runnumber',node)]=0
            self.remote[('spillnumber',node)]=0
            self.remote[('evinspill',node)]=0
            self.remote[('paused',node)]=0

        self.allbuttons=['createbutton','startbutton','pausebutton','stopbutton']
        self.allrunblock=['runtypebutton','runnumberspinbutton','tablexbutton','tableybutton','movetablebutton','filltableposbutton',
                          'runstarttext','runstoptext','showcomments','daqstringentry','pedfrequencyspinbutton',
                          'beamparticlebox','beamenergyentry','beamsigmaxentry','beamsigmayentry',
                          'beamintensityentry','beamtiltxentry','beamtiltyentry']
        self.playlevel=0
        self.global_veto_alarm=False
        self.autostop_max_events=-1
        self.locdqmplots={}
        self.loclargedqmplots={}
        self.dqmplotsimgb_={}

        gtk.rc_parse('.h4gtkrc')
        self.gm = gtk.Builder()
        self.gm.add_from_file("H4GtkGui.glade")
        self.gm.connect_signals(self)
        self.mainWindow = self.gm.get_object("MainWindow")
        self.mainWindow.set_position(gtk.WIN_POS_CENTER_ALWAYS)
        self.set_spinbuttons_properties()
        self.mywaiter = waiter(self.gm)

        if self.sumptuous_browser:
            self.btabs=[]
            BrowserTab(self.gm.get_object('dqmnotebook'),self.btabs,'http://localhost/DQM')
        else:
            self.init_dqm_plots()
            gobject.timeout_add(5000,self.update_dqm_plots)

        self.confdb = DataTakingConfigHandler()
        self.confblock = DataTakingConfig()
        self.confdb.confblock = self.confblock
        self.start_network()

        self.gotostatus('INIT')
        self.mainWindow.connect('destroy',gtk.main_quit)
        self.mainWindow.show_all()

        self.aliveblinkstatus=False
        gobject.timeout_add(1000,self.change_color_blinkingalive)
        self.alarms={}
        self.alarmblinkstatus=False
        gobject.timeout_add(500,self.check_alarm)

        gobject.idle_add(self.update_gui_statuscounters)
        gobject.timeout_add(500,self.update_temperature)

        self.do_check_evinrun_increasing=False
        self.old_evinrun=0
        self.old_evinrun_lastcheck=time.time()
#        gobject.timeout_add(1000,self.check_evinrun_increasing) # TO BE FIXED

        self.videostream()

# NETWORKING
    def start_network(self):
        self.context = Context()
        self.poller = Poller()
        self.sub={}
        for node,addr in self.nodes:
            self.sub[node] = self.context.socket(SUB)
            self.sub[node].connect(addr)
            self.sub[node].setsockopt(SUBSCRIBE,'')
            self.poller.register(self.sub[node],POLLIN)
        self.pub = self.context.socket(PUB)
        self.pub.bind(self.pubsocket_bind_address)
        gobject.idle_add(self.poll_sockets)
        gobject.timeout_add(30000,self.check_keepalive)
        return False
    def poll_sockets(self):
        socks = dict(self.poller.poll(1))
        for node,sock in self.sub.iteritems():
            if (socks.get(sock)):
                message = sock.recv()
                if node in self.keepalive.keys():
                    self.keepalive[node]=True
                self.proc_message(node,message)
        return True
    def check_keepalive(self):
        for node,val in self.keepalive.iteritems():
            if not val:
                self.set_alarm('Lost connection with '+str(node),1)
            else:
                self.unset_alarm('Lost connection with '+str(node))
            self.keepalive[node]=False
        return True
    def check_evinrun_increasing(self):
        if self.do_check_evinrun_increasing and (time.time()-self.old_evinrun_lastcheck>60):
            if self.status['evinrun']<self.old_evinrun:
                self.set_alarm('Problem with increasing nr. of events in run check',1)
            elif self.status['evinrun']==self.old_evinrun:
                self.set_alarm('No events built in the last minute: stuck at %d'%(int(self.old_evinrun),),1)
            else:
                self.unset_alarm('No events built in the last minute')
            self.old_evinrun=self.status['evinrun']
            self.old_evinrun_lastcheck=time.time()
        return True
    def send_message(self,msg,param='',forcereturn=None):
        mymsg=msg
        if not param=='':
            mymsg=str().join([str(mymsg),' ',str(param)])
        if (self.debug):
            self.Log(str(' ').join(('Sending message:',str(mymsg))))
        self.pub.send(mymsg)
        if not forcereturn==None:
            return forcereturn
    def proc_message(self,node,msg):
        if (self.debug):
            newmsg=str(msg)
            self.Log(str(' ').join(('Processing message from',str(node),':',newmsg)))
        if node in self.keepalive.keys():
            self.keepalive[node]=True
        parts = msg.split(' ')
        if len(parts)<1:
            return
        tit = parts[0]
        parts = parts[1:]
        if tit==self.gui_in_messages['status']:
            oldstatus=self.remote[('status',node)]
            for part in parts:
                if part.find('=')<0:
                    continue
                key,val=part.split('=')
                try:
                    self.remote[(key,node)]=int(val)
                except ValueError:
                    self.Log('Impossible to interpret message: <'+msg+'>')
                    True
            self.remote[('status',node)]=self.rsdict[self.remote[('statuscode',node)]]
            if self.remote[('statuscode',node)] in self.remotestatuses_datataking:
                self.remote[('status',node)]='DATATAKING'
            self.update_gui_statuscounters()
            if self.debug:
                if not oldstatus==self.remote[('status',node)]:
                    self.Log('Status change for '+str(node)+': '+str(oldstatus)+' -> '+str(self.remote[('status',node)]))
            if self.remote[('status',node)]=='ERROR':
                self.set_alarm('Node %s in ERROR'%(node,),2)
            if node=='RC':
                self.processrccommand(self.remote[('status',node)])
                self.send_stop_pause_messages()
        elif tit==self.gui_in_messages['log']:
            mymsg = 'Log from '+str(node)+':'
            for p in parts:
                mymsg+=' '+str(p)
            mymsg=mymsg.replace('\n','')
            self.Log(mymsg)
        elif tit==self.gui_in_messages['error']:
            lev = int(parts[0])
            for p in parts[1:]:
                mymsg+=' '+str(p)
            self.set_alarm(mymsg,lev)
        elif tit==self.gui_in_messages['sps']:
            self.flash_sps(str(parts[0]))
        elif tit==self.gui_in_messages['tablepos']:
            self.status['table_status']=(float(parts[0]),float(parts[1]),self.status['table_status'][2])
            self.gm.get_object('tableposlabel').set_text('Table pos. (mm): %.2f / %.2f / %s'%(self.status['table_status'][0],self.status['table_status'][1],self.status['table_status'][2].replace('TAB_',''),))
        elif tit==self.gui_in_messages['tablemoving']:
            self.status['table_status']=(self.status['table_status'][0],self.status['table_status'][1],"TAB_MOVING")
        elif tit==self.gui_in_messages['tabledone']:
            self.status['table_status']=(self.status['table_status'][0],self.status['table_status'][1],"TAB_DONE")
        elif tit==self.gui_in_messages['transfer']:
            if node=='EVTB':
                for part in parts:
                    if part.find('=')<0:
                        continue
                    key,val=part.split('=')
                    if key=='badspills':
                        self.status[key]=int(val)
                    if key=='eventsmerged':
                        self.status[key]=int(val)
                    elif key=='transferTime':
                        transferTime=val # in usec
                    elif key=='transrate_size':
                        transferSize=val # in bytes
                    elif key=='evinrun':
                        self.status['evinrun']=val
                rate = float(transferSize)/1.048576/float(transferTime) # MB/s
                self.status['spillsize']=float(transferSize)/1048576. # MB
                self.status['transferRate']=rate
        elif tit==self.gui_in_messages['spillduration']:
            if node=='RC':
                for part in parts:
                    if part.find('=')<0:
                        continue
                    key,val=part.split('=')
                    if key=='runnumber' and self.status[key]!=int(val):
                        break
                    if key=='spillnumber' and self.status[key]!=int(val):
                        break
                    if key=='spillduration':
                        self.status[key]=float(val)/1000000. # in seconds
                        if val!=0:
                            self.status['trigrate']=float(self.remote[('evinspill',node)])/self.status[key]
                        else:
                            self.status['trigrate']=0

# RUN STATUS AND COUNTERS, GUI ELEMENTS SENSITIVITY AND MANIPULATION
    def update_gui_statuscounters(self):
        self.status['runnumber']=self.remote[('runnumber','RC')]
        self.status['spillnumber']=self.remote[('spillnumber','RC')]
        self.status['evinspill']=self.remote[('evinspill','RC')]
        if not self.gm.get_object('runstatuslabel').get_text().split(' ')[-1]==self.remote[('status','RC')]:
            self.gm.get_object('runstatuslabel').set_text(str(' ').join(('Run controller:',self.remote[('status','RC')])))
            self.flash_widget(self.gm.get_object('runstatusbox'),'green')
        if 'RO1' in [x[0] for x in self.nodes]:
            self.gm.get_object('ro1label').set_text( str(' ').join(('DRO 1:',self.remote[('status','RO1')])))
        if 'RO2' in [x[0] for x in self.nodes]:
            self.gm.get_object('ro2label').set_text( str(' ').join(('DRO 2:',self.remote[('status','RO2')])))
        if 'EVTB' in [x[0] for x in self.nodes]:
            self.gm.get_object('evtblabel').set_text(str(' ').join(('Event Builder:',self.remote[('status','EVTB')])))
        if 'DRCV1' in [x[0] for x in self.nodes]:
            self.gm.get_object('drcv1label').set_text(str(' ').join(('DRCV 1:',self.remote[('status','DRCV1')])))
        if 'DRCV2' in [x[0] for x in self.nodes]:
            self.gm.get_object('drcv2label').set_text(str(' ').join(('DRCV 2:',self.remote[('status','DRCV2')])))

        self.gm.get_object('runnumberlabel').set_text(str().join(['Run number: ',str(self.status['runnumber'])]))
        self.gm.get_object('spillnumberlabel').set_text(str().join(['Spill number: ',str(self.status['spillnumber'])]))
        self.gm.get_object('badspillslabel').set_text(str().join(['Nr. of bad spills: ',str(self.status['badspills'])]))
        self.gm.get_object('mergedevlabel').set_text(str().join(['Merged ev. in spill: ',str(self.status['eventsmerged'])]))
        self.gm.get_object('evinrunlabel').set_text(str().join(['Total #events in run: ',str(self.status['evinrun'])]))
        self.gm.get_object('evinspilllabel').set_text(str().join(['Nr. of events in spill: ',str(self.status['evinspill'])]))
        self.gm.get_object('spillsizelabel').set_text(str().join(['Spill size (MB): ',str('%.1f'%(self.status['spillsize'],))]))
        self.gm.get_object('transfratelabel').set_text(str().join(['Transfer rate (MB/s): ',str('%.1f'%(self.status['transferRate'],))]))
        self.gm.get_object('spilldurationlabel').set_text(str().join(['Spill duration (s): ',str('%.3f'%(self.status['spillduration'],))]))
        self.gm.get_object('trigratelabel').set_text(str().join(['Trigger rate (Hz): ',str('%.1f'%(self.status['trigrate'],))]))
        temptext = ' Sensors temp. (°C): '
        for i in xrange(len(self.status['temperatures'])):
            if i>0:
                temptext+='/ '
            mytemp = ''
            if self.status['temperatures'][i]!=None:
                mytemp = '%.2f '%(self.status['temperatures'][i],)
            temptext+=mytemp
        self.gm.get_object('templabel').set_text(temptext)
        temptext='Humidity ('+'%'+'): '
        if self.status['humidity']:
            temptext+='%.2f'%(self.status['humidity'],)
        self.gm.get_object('humlabel').set_text(temptext)
        temptext='Dew point (°C): '
        if self.status['dewpoint']:
            temptext+='%.2f'%(self.status['dewpoint'],)
        self.gm.get_object('dewpointlabel').set_text(temptext)
        temptext='Lauda temp. (°C): '
        if self.status['laudatemp']:
            temptext+='%.2f '%(self.status['laudatemp'],)
        self.gm.get_object('laudatemplabel').set_text(temptext)
        return True

    def set_sens(self,wids,value):
        for wid in wids:
            if not self.gm.get_object(str(wid)):
                self.Log(str().join(('ERROR ',wid)))
            self.gm.get_object(str(wid)).set_sensitive(value)
    def set_label(self,wid,value):
        self.gm.get_object(str(wid)).set_label(str(value))

    def set_spinbuttons_properties(self):
        button = self.gm.get_object('runnumberspinbutton')
        button.set_value(0)
        button.set_numeric(True)
        button.set_increments(1,10)
        button.set_range(0,100000)
        button.set_wrap(False)
        button = self.gm.get_object('pedfrequencyspinbutton')
        button.set_value(0)
        button.set_numeric(True)
        button.set_increments(100,1000)
        button.set_range(0,1000000)
        button.set_wrap(False)
        self.init_gtkcombobox(self.gm.get_object('runtypebutton'),['PHYSICS','PEDESTAL','LED'])
        self.init_gtkcombobox(self.gm.get_object('filltableposbutton'),[None]+self.tableposdictionary.keys())
        self.init_gtkcombobox(self.gm.get_object('beamparticlebox'),['Electron','Positron','Pion','Muon'])

     # GtkComboBoxEntry (deprecated)
#    def read_gtkcomboboxentry_string(self,button):
#        return str(button.child.get_text())
#    def update_comboboxentry(self,button):
#        output = self.read_gtkcombobox_status(button)
#        if output:
#            newtext=str(output)
#            button.child.set_text(newtext)


    # GtkSpinButton
    def set_gtkspinbutton(self,button,value):
        button.set_value(value or 0)

    # GtkEntry
    def set_gtkentry(self,button,value):
        out = ''
        myval=str(value)
        if myval!='' and myval!='None':
            out=myval
        button.set_text(out)
    def get_gtkentry(self,button):
        return button.get_text()

    # GtkTextBuffer
    def get_text_from_textbuffer(self,bufname):
        buf=self.gm.get_object(bufname)
        out=buf.get_text(buf.get_start_iter(),buf.get_end_iter())
        return out

    # GtkComboBox
    def set_gtkcombobox_entry(self,button,newentry):
        for index in xrange(len(button.get_model())):
            if newentry==button.get_model()[index][0]:
                button.set_active(index)
    def read_gtkcombobox_status(self,button):
        tree_iter = button.get_active_iter()
        thisentry=None
        if tree_iter:
            model = button.get_model()
            thisentry = model[tree_iter][0]
        return thisentry
    def set_gtkcombobox_options(self,button,mylist):
        entrylist = gtk.ListStore(str)
        for entry in mylist:
            entrylist.append([entry])
        button.set_model(entrylist)
        button.set_active(-1)
    def init_gtkcombobox(self,button,mylist):
        self.set_gtkcombobox_options(button,mylist) 
        renderer_text = gtk.CellRendererText()
        button.pack_start(renderer_text, True)
        button.add_attribute(renderer_text, "text", 0)       



# ALARMS
    def Log(self,*args):
        mytext_=datetime.datetime.now().strftime('%d.%m.%y %H:%M:%S')
        for arg in args:
            mytext_+=' '+str(arg)
        mybuffer=self.gm.get_object('rclogbuffer')
        mybuffer.insert(mybuffer.get_end_iter(),str(mytext_)+'\n')
    def on_rclogview_size_allocate(self,*args):
        adj=self.gm.get_object('scrolledwindow3').get_vadjustment()
        adj.set_value(adj.get_upper()-adj.get_page_size()) 
    def set_alarm(self,msg='Error_Generic',level=1):
        if self.global_veto_alarm:
            return
        if level==0:
            self.unset_alarm(msg)
            return
        else:
            setit=False
            if msg not in self.alarms.keys():
                setit=True
            elif self.alarms[msg]!=level:
                setit=True
            if setit:
                self.Log('Setting alarm %d: '%(level,)+msg)
                if level>=2:
                    if self.activatesounds:
                        self.bark(20)
                elif level>=1:
                    if self.activatesounds:
                        self.beep(2)
        self.alarms[msg]=level
    def unset_alarm(self,msg):
        if msg in self.alarms.keys():
            self.Log('Clearing alarm: '+msg)
        self.alarms.pop(msg,None)
    def clear_alarms(self):
        self.alarms.clear()
        self.barktimes=0
        self.beeptimes=0
        self.playlevel=0
    def check_alarm(self):
        if self.alarmblinkstatus==False:
            color=None
            mylevel=0
            if not len(self.alarms)==0:
                mylevel = max(self.alarms.itervalues())
                if mylevel>=2:
                    color=gtk.gdk.color_parse('red')
                elif mylevel>=1:
                    color=gtk.gdk.color_parse('yellow')
            self.gm.get_object('alarmbox').modify_bg(gtk.STATE_NORMAL,color)
            if mylevel>=1:
                self.gm.get_object('MainWindow').modify_bg(gtk.STATE_NORMAL,color)
        else:
            self.gm.get_object('alarmbox').modify_bg(gtk.STATE_NORMAL,None)
            self.gm.get_object('MainWindow').modify_bg(gtk.STATE_NORMAL,None)
        self.alarmblinkstatus=not self.alarmblinkstatus
        return True
    def change_color_blinkingalive(self):
        if self.aliveblinkstatus==False:
            self.gm.get_object('alivebox').modify_bg(gtk.STATE_NORMAL,gtk.gdk.color_parse("green"))
        else:
            self.gm.get_object('alivebox').modify_bg(gtk.STATE_NORMAL,None)
        self.aliveblinkstatus = not self.aliveblinkstatus
        return True
    def color_widget(self,widget,color=None,forcereturn=None):
        if (color=='' or color==None):
            widget.modify_bg(gtk.STATE_NORMAL,None)
        else:
            widget.modify_bg(gtk.STATE_NORMAL,gtk.gdk.color_parse(color))
    def flash_widget(self,widget,color,duration=300):
        self.color_widget(widget,color)
        gobject.timeout_add(300,self.color_widget,widget,None,False)
    def flash_sps(self,signal):
        my=signal
        my+='box'
        self.flash_widget(self.gm.get_object(my),'orange')


# EXEC ACTIONS
    def send_stop_pause_messages(self):
#        rc=self.remote[('statuscode','RC')]
#        if rc in self.remotestatuses_running:
        if self.wanttostop:
            self.stoprun()
        elif self.wanttopause:
            self.pauserun()
    def processrccommand(self,command):
        rc=self.remote[('statuscode','RC')]
        if self.remote[('paused','RC')]==1:
            self.gotostatus('PAUSED')
        elif rc in self.remotestatuses_stopped:
            if self.status['localstatus'] in ['RUNNING','PAUSED']:
                if not self.globalstopconsent:
                    self.set_alarm('RUN STOPPED WITHOUT USER REQUEST',2)
                    self.confblock.r['run_exit_code']=1
                else:
                    self.confblock.r['run_exit_code']=0
                self.gotostatus('STOPPED')
                self.globalstopconsent=False
        else:
            self.gotostatus('RUNNING')
        if rc==self.remotestatus_endofspill:
            if (self.autostop_max_events>0) and (int(self.status['evinrun'])>int(self.autostop_max_events)):
                print self.status['evinrun'],self.autostop_max_events
                self.on_stopbutton_clicked()
    def remotecheckpaused(self,whatiwant):
        return (self.remote[('paused','RC')]==whatiwant)

    def createrun(self):
        if self.status['localstatus']=='CREATED':
            self.gotostatus('INIT')
            return
        self.get_gui_confblock()
        self.confblock = self.confdb.read_from_db(runnr=self.confblock.r['run_number'])
        self.gotostatus('CREATED')
        self.confblock.r['run_end_user_comment']=''
        self.confblock.r['run_comment']=''
        self.update_gui_confblock()

    def startrun(self):
        self.get_gui_confblock()
#        if not self.table_is_ok(self.confblock.r['table_horizontal_position'],self.confblock.r['table_vertical_position']):
#            self.Log('Table condition does not allow to start run: have you forgotten to actually move the table? Current situation:')
#            self.Log(str(self.status['table_status']))
#            return
#        #        if self.confblock.t['run_type_description'] in ['PEDESTAL','LED']:
        if self.confblock.t['ped_frequency']==0:
            self.Log('Beware: You have set a number of triggers per spill to 0: for PEDESTAL, LED runs or without HW spill signals you will produce empty spills')
        #            return
        for key,node,val in [(a[0],a[1],b) for a,b in self.remote.iteritems()]:
            if key!='statuscode':
                continue
            if node in ['RC','RO1','RO2','EVTB']:
                if val!=self.remotestatus_betweenruns:
                    self.Log('Node %s not ready for STARTRUN'%(str(node),))
                    return
        self.status['evinrun']=0
        self.confblock.d['daq_gitcommitid']=self.get_latest_commit()
        self.confblock=self.confdb.add_into_db(self.confblock)
        self.update_gui_confblock()
        self.Log('Sending START for run '+str(self.confblock.r['run_number']))
        self.send_message(str(' ').join([str(self.gui_out_messages['startrun']),str(self.confblock.r['run_number']),str(self.confblock.t['run_type_description']),str(self.confblock.t['ped_frequency'])]))        

    def reconfig(self):
        for key,node,val in [(a[0],a[1],b) for a,b in self.remote.iteritems()]:
            if key!='statuscode':
                continue
            if node in ['RC','RO1','RO2','EVTB']:
                if val!=self.remotestatus_betweenruns:
                    self.Log('Cannot issue RECONFIG for node %s'%(str(node),))
                    return
        self.send_message(self.gui_out_messages['reconfig'])       

    def pauserun(self):
        if self.status['localstatus']=='RUNNING':
            self.wanttopause=False
            self.Log('Sending PAUSE for run '+str(self.confblock.r['run_number']))
            self.send_message(self.gui_out_messages['pauserun'])

    def resumerun(self):
        if self.status['localstatus']=='PAUSED':
            self.Log('Sending RESUME for run '+str(self.confblock.r['run_number']))
            self.send_message(self.gui_out_messages['restartrun'])

    def remstatus_is(self,whichstatus):
        return (self.remote[('statuscode','RC')] in whichstatus)

    def stoprun(self):
        self.globalstopconsent=True
        self.wanttostop=False
        self.autostop_max_events=-1
        self.gm.get_object('maxevtoggle').set_active(False)
        self.gm.get_object('maxevtoggle').modify_bg(gtk.STATE_NORMAL,None)
        self.gm.get_object('maxevtoggle').modify_bg(gtk.STATE_PRELIGHT,None)
        self.Log('Sending STOP for run '+str(self.confblock.r['run_number']))
        self.send_message(self.gui_out_messages['stoprun'])
        self.gui_go_to_runnr(self.status['runnumber'])

    def closerun(self):
        self.get_gui_confblock()
        self.confblock.r['run_nevents']=self.status['evinrun']
        self.confblock=self.confdb.update_to_db(self.confblock)
        self.gotostatus('INIT')

# PROCESS SIGNALS
    def on_buttonquit_clicked(self,*args):
        self.mywaiter.reset()
        self.mywaiter.set_layout('Do you want to quit the GUI?','Cancel','Yes',color='orange')
        self.mywaiter.set_exit_func(gtk.main_quit,[])
        self.mywaiter.run()        
    def on_quitbuttonRC_clicked(self,*args):
        self.Log("Request to quit run controller from GUI user")
        self.mywaiter.reset()
        self.mywaiter.set_layout('<b>Do you want to quit the DAQ?</b>','Cancel','Yes',color='orange')
        self.mywaiter.set_exit_func(self.send_message,[self.gui_out_messages['die']])
        self.mywaiter.run()        
    def on_reconfigbuttonRC_clicked(self,*args):
        self.Log("Request to reconfig controller from GUI user")
        self.mywaiter.reset()
        self.mywaiter.set_layout('<b>Do you want to reconfig the DAQ?</b>','Cancel','Yes',color='orange')
        self.mywaiter.set_exit_func(self.reconfig,[])
        self.mywaiter.run()        
    def on_createbutton_clicked(self,*args):
        self.createrun()
    def on_startbutton_clicked(self,*args):
        message = 'Do you want to start?'
        self.mywaiter.reset()
        self.mywaiter.set_layout(message,'Cancel','Start',color='green')
        self.mywaiter.set_exit_func(self.startrun,[])
        self.mywaiter.run()


    def on_pausebutton_clicked(self,*args):
        if self.status['localstatus']=='RUNNING':
            message = 'Do you want to pause?'
        elif self.status['localstatus']=='PAUSED':
            message = 'Do you want to resume?'
        self.mywaiter.reset()
        self.mywaiter.set_layout(message,'Cancel','Yes',color='orange')
        if self.status['localstatus']=='RUNNING':
            self.mywaiter.set_exit_func(self.set_wanttopause,[])
        elif self.status['localstatus']=='PAUSED':
            self.mywaiter.set_exit_func(self.resumerun,[])
        self.mywaiter.run()
    def on_stopbutton_clicked(self,*args):
        if self.status['localstatus']=='STOPPED':
            self.closerun()
        else:
            self.mywaiter.reset()
            self.mywaiter.set_layout('Do you want to stop?','Cancel','Yes',color='orange')
            self.mywaiter.set_exit_func(self.set_wanttostop,[])
            self.mywaiter.run()
    def set_wanttostop(self,*args):
        self.wanttostop=True
    def set_wanttopause(self,*args):
        self.wanttopause=True
    def gui_go_to_runnr(self,newrunnr):
        if not self.confdb.run_exists(newrunnr):
            return False
        self.confblock=self.confdb.read_from_db(runnr=newrunnr)
        self.update_gui_confblock()
        return True
    def on_runnumberspinbutton_value_changed(self,*args):
        newnr=int(self.gm.get_object('runnumberspinbutton').get_value())
        if newnr>=0:
            isgood = self.gui_go_to_runnr(newnr)
            if not isgood:
                self.Log('Run %s does not exist' % str(newnr))
    def save_runtextbuffer(self,*args):
        self.get_gui_confblock()
        if not self.confblock.r['run_number']==self.status['runnumber']:
            return
        self.confblock=self.confdb.update_to_db(self.confblock,onlycomment=True)

    def on_filltableposbutton_changed(self,wid,*args):
        pos = self.tableposdictionary.get(self.read_gtkcombobox_status(wid),None)
        if pos==None:
            return
        x,y = pos
        self.set_gtkentry(self.gm.get_object('tablexbutton'),x)
        self.set_gtkentry(self.gm.get_object('tableybutton'),y)

# DATATAKINGCONFIG MANIPULATION
    def update_gui_confblock(self):
        self.set_gtkcombobox_entry(self.gm.get_object('runtypebutton'),self.confblock.t['run_type_description'])
        self.set_gtkspinbutton(self.gm.get_object('runnumberspinbutton'),(self.confblock.r['run_number']))
        self.set_gtkentry(self.gm.get_object('tablexbutton'),(self.confblock.r['table_horizontal_position']))
        self.set_gtkentry(self.gm.get_object('tableybutton'),(self.confblock.r['table_vertical_position']))
        self.set_gtkspinbutton(self.gm.get_object('pedfrequencyspinbutton'),(self.confblock.t['ped_frequency']))
        self.set_gtkentry(self.gm.get_object('runstarttext'),(self.confblock.r['run_start_user_comment']))
        self.set_gtkentry(self.gm.get_object('runstoptext'),(self.confblock.r['run_end_user_comment']))
        self.set_gtkentry(self.gm.get_object('daqstringentry'),(self.confblock.d['daq_type_description']))
        self.set_gtkentry(self.gm.get_object('beamenergyentry'   ),(self.confblock.b['beam_energy']))
        self.set_gtkentry(self.gm.get_object('beamsigmaxentry'   ),(self.confblock.b['beam_horizontal_width']))
        self.set_gtkentry(self.gm.get_object('beamsigmayentry'   ),(self.confblock.b['beam_vertical_width']))
        self.set_gtkentry(self.gm.get_object('beamintensityentry'),(self.confblock.b['beam_intensity']))
        self.set_gtkentry(self.gm.get_object('beamtiltxentry'    ),(self.confblock.b['beam_horizontal_tilt']))
        self.set_gtkentry(self.gm.get_object('beamtiltyentry'    ),(self.confblock.b['beam_vertical_tilt']))
        self.set_gtkcombobox_entry(self.gm.get_object('beamparticlebox'),self.confblock.b['beam_particle'])    
        self.set_gtkentry(self.gm.get_object('runtextbuffer'),self.confblock.r['run_comment'])
    def get_gui_confblock(self):
        self.confblock.r['run_number']=int(self.gm.get_object('runnumberspinbutton').get_value())
        self.confblock.r['table_horizontal_position']=float(self.gm.get_object('tablexbutton').get_text())
        self.confblock.r['table_vertical_position']=float(self.gm.get_object('tableybutton').get_text())
        self.confblock.r['run_start_user_comment']=self.gm.get_object('runstarttext').get_text()
        self.confblock.r['run_end_user_comment']=self.gm.get_object('runstoptext').get_text()
        self.confblock.t['run_type_description']=self.read_gtkcombobox_status(self.gm.get_object('runtypebutton'))
        self.confblock.t['ped_frequency']         =self.gm.get_object('pedfrequencyspinbutton').get_value()
        self.confblock.d['daq_type_description']=self.gm.get_object('daqstringentry').get_text()
        self.confblock.b['beam_particle']         =self.read_gtkcombobox_status(self.gm.get_object('beamparticlebox'))
        self.confblock.b['beam_energy']           =self.gm.get_object('beamenergyentry'   ).get_text()
        self.confblock.b['beam_horizontal_width'] =self.gm.get_object('beamsigmaxentry'   ).get_text()
        self.confblock.b['beam_vertical_width']   =self.gm.get_object('beamsigmayentry'   ).get_text()
        self.confblock.b['beam_intensity']        =self.gm.get_object('beamintensityentry').get_text()
        self.confblock.b['beam_horizontal_tilt']  =self.gm.get_object('beamtiltxentry'    ).get_text()
        self.confblock.b['beam_vertical_tilt']    =self.gm.get_object('beamtiltyentry'    ).get_text()
        self.confblock.r['run_comment'] = self.get_text_from_textbuffer('runtextbuffer')

# FSM
    def gotostatus(self,status):
        if self.debug:
            self.Log(str().join(['Local status:',self.status['localstatus'],'->',status]))
        if self.status['localstatus']==status:
                return
        self.status['localstatus']=status
        if status=='INIT':
            self.confblock=self.confdb.read_from_db(runnr=self.confdb.get_highest_run_number())
            self.update_gui_confblock()
        if status=='INIT':
            self.set_sens(self.allbuttons,False)
            self.set_sens(self.allrunblock,False)
            self.set_sens(['runnumberspinbutton'],True)
            self.set_sens(['createbutton'],True)
            self.set_label('createbutton','CREATE RUN')
            self.set_label('startbutton','START RUN')
            self.set_label('pausebutton','PAUSE RUN')
            self.set_label('stopbutton','STOP RUN')
            self.gm.get_object('runnumberspinbutton').set_visibility(True)
        elif status=='CREATED':
            self.set_sens(self.allbuttons,False)
            self.set_sens(self.allrunblock,True)
            self.set_sens(['runnumberspinbutton','runstoptext'],False)
            self.set_sens(['createbutton','startbutton','movetablebutton'],True)
            self.set_label('createbutton','CANCEL')
            self.set_label('startbutton','START RUN')
            self.set_label('pausebutton','PAUSE RUN')
            self.set_label('stopbutton','STOP RUN')
            self.gm.get_object('runnumberspinbutton').set_visibility(False)
        elif status=='RUNNING':
            self.set_sens(self.allbuttons,False)
            self.set_sens(self.allrunblock,False)
            self.set_sens(['runnumberspinbutton'],True)
            self.set_sens(['showcomments','runtext'],True)
            self.set_sens(['pausebutton','stopbutton'],True)
            self.set_label('createbutton','CREATE RUN')
            self.set_label('startbutton','START RUN')
            self.set_label('pausebutton','PAUSE RUN')
            self.set_label('stopbutton','STOP RUN')
            self.gm.get_object('runnumberspinbutton').set_visibility(True)
        elif status=='PAUSED':
            self.set_sens(self.allbuttons,False)
            self.set_sens(self.allrunblock,False)
            self.set_sens(['runnumberspinbutton'],True)
            self.set_sens(['showcomments','runtext'],True)
            self.set_sens(['pausebutton','stopbutton'],True)
            self.set_label('createbutton','CREATE RUN')
            self.set_label('startbutton','START RUN')
            self.set_label('pausebutton','RESUME RUN')
            self.set_label('stopbutton','STOP RUN')
            self.gm.get_object('runnumberspinbutton').set_visibility(True)
        elif status=='STOPPED':
            self.set_sens(self.allbuttons,False)
            self.set_sens(self.allrunblock,False)
            self.set_sens(['showcomments','runtext'],True)
            self.set_sens(['stopbutton'],True)
            self.set_sens(['runstoptext'],True)
            self.set_label('createbutton','CREATE RUN')
            self.set_label('startbutton','START RUN')
            self.set_label('pausebutton','PAUSE RUN')
            self.set_label('stopbutton','CLOSE RUN')
            self.gm.get_object('runnumberspinbutton').set_visibility(True)

        if status=='RUNNING':
            self.do_check_evinrun_increasing=True
            self.old_evinrun=0
            self.old_evinrun_lastcheck=time.time()
        else:
            self.do_check_evinrun_increasing=False
            self.old_evinrun=0
            self.old_evinrun_lastcheck=time.time()

#        self.set_sens(['tablexbutton','tableybutton','movetablebutton','filltableposbutton'],True) # WARNING: THIS SHOULD NOT BE LIKE THIS!!!

# TABLE POSITION HANDLING
    def get_table_position(self):
        return self.status['table_status']
    def set_table_position(self,newx,newy):
        if self.get_table_position()[2]!='TAB_DONE':
            self.Log('ERROR: trying to move table while table is not stopped')
            return False
        if self.status['table_status']!=(newx,newy,'TAB_DONE'):
            self.status['table_status']=(self.status['table_status'][0],self.status['table_status'][1],'SENT_MOVE_ORDER')
            self.Log('SENDING TABLE TO %s %s' % (newx,newy,))
            self.send_message('SET_TABLE_POSITION %s %s' % (newx,newy,))
        message='Waiting for table to move to '+str(newx)+' '+str(newy)
        self.mywaiter.reset()
        self.mywaiter.set_layout(message,None,'Force ACK table moving',color='green')
        self.mywaiter.set_condition(self.table_is_ok,[newx,newy])
        self.mywaiter.run()
    def on_movetablebutton_clicked(self,*args):
        x=float(self.gm.get_object('tablexbutton').get_text())
        y=float(self.gm.get_object('tableybutton').get_text())
        self.set_table_position(x,y)
    def table_is_ok(self,newx,newy):
        if self.get_table_position()==(newx,newy,'TAB_DONE'):
            return True
        return False
    def stop_table(self):
        if self.get_table_position()[2]!='TAB_DONE':
            self.Log('Stopping Table')
#            self.send_message('STOP_TABLE')
        self.mywaiter.reset()
        self.mywaiter.set_layout('Waiting for stopping table',None,'Force ACK table stop', color='green')
        self.mywaiter.set_condition(self.get_table_position()[2]!='TAB_DONE',[self.get_table_position()[0],self.get_table_position()[1]])
        self.mywaiter.run()
    def on_stoptablebutton_clicked(self,*args):
        self.stop_table()

# GENERAL INPUT WINDOW
    def generalinputwindow(self,label,func):
        self.set_label('inputwindowlabel',label)
        self.set_gtkentry(self.gm.get_object('inputwindowentry'),'')
        self.gm.get_object('InputWindow').show()
        self.inputwindowentryfunction=func
    def on_inputwindowentry_activate(self,*args):
        message = self.gm.get_object('inputwindowentry').get_text()
        self.inputwindowentryfunction(message)
    def on_inputwindowquit_clicked(self,*args):
        self.gm.get_object('InputWindow').hide()

    def on_dummyguibutton_clicked(self,*args):
        self.generalinputwindow('Send command with DummyGUI',self.send_message)
    def on_clearalarmbutton_clicked(self,*args):
        self.clear_alarms()
    def on_vetoalarmbutton_toggled(self,*args):
        self.global_veto_alarm=self.gm.get_object('vetoalarmbutton').get_active()
        color=None
        if self.global_veto_alarm:
            color=gtk.gdk.color_parse('orange')
            self.clear_alarms()
        self.gm.get_object('vetoalarmbutton').modify_bg(gtk.STATE_ACTIVE,color)
        self.gm.get_object('vetoalarmbutton').modify_bg(gtk.STATE_PRELIGHT,color)



# SOUNDS
    def bark(self,times):
        self.barktimes=3*times
        gobject.timeout_add(600,self.bark_helper)
    def bark_helper(self):
        if self.playlevel>2:
            return False
        if self.barktimes<=0:
            self.playlevel=0
            return False
        self.playlevel=2
        if not self.barktimes%3==1:
            soundcom = ('filesrc location=%s ! decodebin2 ! autoaudiosink') % \
            '/usr/share/sounds/gnome/default/alerts/bark.ogg'
            self.play = gst.parse_launch(soundcom)
            self.play.set_state(gst.STATE_PLAYING)
        self.barktimes-=1;
        return True
    def beep(self,times,freq=400):
        self.beeptimes=2*times
        soundcom = ('audiotestsrc freq=%d ! decodebin2 ! autoaudiosink') % freq
        self.play = gst.parse_launch(soundcom)
        self.playlevel=1
        gobject.timeout_add(2000,self.beep_helper,self.play,self.beeptimes)
    def beep_helper(self,p,beeptimes):
        if self.playlevel>1:
            return False
        if self.beeptimes<=0:
            self.playlevel=0
            return False
        if self.beeptimes%2==0:
            p.set_state(gst.STATE_PLAYING)
        else:
            p.set_state(gst.STATE_PAUSED)
        self.beeptimes-=1;
        return True


# WAITING WINDOW
    def on_waitbutton1_clicked(self,*args):
        self.mywaiter.on_waitbutton1_clicked_(args)
    def on_waitbutton2_clicked(self,*args):
        self.mywaiter.on_waitbutton2_clicked_(args)

# PLOT DISPLAY WINDOW
    def on_maxevtoggle_toggled(self,button,*args):
        if button.get_active():
            self.autostop_max_events=int(self.gm.get_object('maxeventry').get_text())
            self.gm.get_object('maxevtoggle').modify_bg(gtk.STATE_ACTIVE,gtk.gdk.color_parse('orange'))
            self.gm.get_object('maxevtoggle').modify_bg(gtk.STATE_PRELIGHT,gtk.gdk.color_parse('orange'))
        else:
            self.autostop_max_events=-1
            self.gm.get_object('maxevtoggle').modify_bg(gtk.STATE_NORMAL,None)
            self.gm.get_object('maxevtoggle').modify_bg(gtk.STATE_PRELIGHT,None)

    def update_temperature(self):
        myenv = self.confdb.get_latest_environment()
        self.status['temperatures']=[myenv['T1'],myenv['T2'],myenv['T3'],myenv['T4'],myenv['T5']]
        self.status['humidity']=myenv['Humidity']
        self.status['dewpoint']=myenv['DewPoint']
        myenv2 = self.confdb.get_latest_chillerreading()
        self.status['laudatemp']=myenv2['chil_tmon']
        return True

    def get_latest_commit(self):
        p1 = Popen(['git','--git-dir=../H4DAQ/.git','log','--pretty=format:\"%H\"'], stdout=PIPE)
        p2 = Popen(['head', '-n 1'], stdin=p1.stdout, stdout=PIPE)
        p1.stdout.close()
        output = p2.communicate()[0]
        output=output.replace('\n','')
        output=output.replace('\"','')
        print 'DAQ commit id = ',str(output)
        return str(output)

    def init_dqm_plots(self):
        nb = self.gm.get_object('dqmnotebook')
        tabnames=[]
        scrollwin={}
        myindex=0
        for tabname,plotname,largeplotname in self.dqmplots:
            if tabname not in tabnames:
                scrollwin[tabname] = gtk.ScrolledWindow()
                scrollwin[tabname].set_policy(gtk.POLICY_NEVER,gtk.POLICY_AUTOMATIC)
                mylabel = gtk.Label(tabname)
                nb.append_page(scrollwin[tabname],mylabel)
                tabnames.append(tabname)
                scrw=scrollwin[tabname]
                tab = gtk.Table(1,3,True)
                scrw.add_with_viewport(tab)
                myindex=0
            evtb = gtk.EventBox()
            imgb = gtk.Image()
            evtb.add(imgb)
            x=int(myindex)%3
            y=int(myindex)/3
            if y>=int(tab.get_property('n-rows')):
                tab.resize(y+1,3)
            tab.attach(evtb,x,x+1,y,y+1)
            locname=plotname.split('/')[-1]
            loclargename=largeplotname.split('/')[-1]
            self.dqmplotsimgb_[plotname]=imgb
            self.locdqmplots[plotname]=self.geturlfile(plotname)
            self.loclargedqmplots[plotname]=self.geturlfile(largeplotname)
            handler_id = evtb.connect('button-press-event',self.open_window_image_clicked,self.loclargedqmplots[plotname])
            myindex+=1
        self.update_dqm_plots()


    def update_dqm_plots(self):
        for tabname,plotname,largeplotname in self.dqmplots:
            self.locdqmplots[plotname]=self.geturlfile(plotname)
            self.loclargedqmplots[plotname]=self.geturlfile(largeplotname)
            self.dqmplotsimgb_[plotname].set_from_file(self.locdqmplots[plotname])

    def geturlfile(self,path):
        if not path:
            return None
        if path.find('http://')!=-1:
            newname='tmp/'+path.split('/')[-1]
            urllib.urlretrieve(path,newname)
        else:
            newname=path
        return newname


    def on_tempeventbox_button_press_event(self,*args):
        self.open_window_image_clicked(imagefile=self.geturlfile(self.temperatureplot))
    def on_image_clicked_buttonpressev(self,wid,ev,im=None):
        self.open_window_image_clicked(imagefile=im)

    def open_window_image_clicked(self,wid=None,ev=None,imagefile=None,*args):
        if imagefile==None or imagefile=='':
            return
        win = gtk.Window()
        win.set_position(gtk.WIN_POS_MOUSE)
        evtb = gtk.EventBox()
        win.add(evtb)
        imgb = gtk.Image()
        imgb.set_from_file(imagefile)
        evtb.add(imgb)
        evtb.connect('button-press-event',self.closewinparent)
        win.show_all()
    def closewinparent(self,wid,*args):
        wid.get_parent_window().destroy()

    def on_syncclocksbutton_clicked(self,*args):
        self.run_script(self.scripts.get('sync_clocks',None))
    def on_freespacebutton_clicked(self,*args):
        self.run_script(self.scripts.get('free_space',None))
    def on_startdaemonsbutton_clicked(self,*args):
        self.run_script(self.scripts.get('start_daemons',None),True)
    def on_killdaemonsbutton_clicked(self,*args):
        self.run_script(self.scripts.get('kill_daemons',None),True)

    def on_showcomments_clicked(self,*args):
        if (self.status['localstatus'] in ['RUNNING','PAUSED','STOPPED']) and int(self.gm.get_object('runnumberspinbutton').get_value())==self.status['runnumber']:
            self.gm.get_object('LogWindow').show()
    def on_logwindowclose_clicked(self,*args):
        self.gm.get_object('LogWindow').hide()
        self.save_runtextbuffer()

    def run_script(self,script=None,alwaysallow=False):
        self.Log('Requesting to run script '+script)
        if script==None or script=='':
            return
        self.mywaiter.reset()
        self.mywaiter.set_layout('<b>Do you really want to run '+script+'?</b>','Cancel','Run',color='orange')
        self.mywaiter.set_exit_func(self.run_script_helper,[script,alwaysallow])
        self.mywaiter.run()
    def run_script_helper(self,script=None,alwaysallow=False):
        if not alwaysallow:
            if self.status['localstatus']=='RUNNING':
                self.Log('Script execution not allowed while taking data!')
                return
        self.Log('WARNING: executing '+script)
        line = ['bash']
        for part in script.split(' '):
            line.append(part)
        p1 = Popen(line, stdout=PIPE)
        output = p1.communicate()[0]
        self.Log(output)



    def videostream(self):
        gtk.gdk.threads_enter()
        nb = self.gm.get_object('dqmnotebook')

        self.webcamarea = gtk.DrawingArea()
        nb.prepend_page(self.webcamarea,gtk.Label('Webcam 2'))
        nb.show_all()
        self.player = gst.parse_launch('souphttpsrc location=http://axisminn02/mjpg/video.mjpg ! decodebin2 ! xvimagesink')
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.deal_with_message)
        bus.enable_sync_message_emission()
        bus.connect("sync-message::element", self.sync_message)
        self.player.set_state(gst.STATE_PLAYING)

        self.webcamarea2 = gtk.DrawingArea()
        nb.prepend_page(self.webcamarea2,gtk.Label('Webcam 1'))
        nb.show_all()
        self.player2 = gst.parse_launch('souphttpsrc location=http://axisminn01/mjpg/video.mjpg ! decodebin2 ! xvimagesink')
        bus2 = self.player2.get_bus()
        bus2.add_signal_watch()
        bus2.connect("message", self.deal_with_message2)
        bus2.enable_sync_message_emission()
        bus2.connect("sync-message::element", self.sync_message2)
        self.player2.set_state(gst.STATE_PLAYING)

        gtk.gdk.threads_leave()

    def deal_with_message(self, bus, message):
        gtk.gdk.threads_enter()
        if message.type in [gst.MESSAGE_EOS,gst.MESSAGE_ERROR]:
            self.player.set_state(gst.STATE_NULL)
        gtk.gdk.threads_leave()

    def deal_with_message2(self, bus, message):
        gtk.gdk.threads_enter()
        if message.type in [gst.MESSAGE_EOS,gst.MESSAGE_ERROR]:
            self.player2.set_state(gst.STATE_NULL)
        gtk.gdk.threads_leave()

    def sync_message(self, bus, message):
        if message.structure is None:
            return
        gtk.gdk.threads_enter()
        message_name = message.structure.get_name()
        if message_name == "prepare-xwindow-id":
            imagesink = message.src
            imagesink.set_property("force-aspect-ratio", True)
            imagesink.set_xwindow_id(self.webcamarea.window.xid)
        gtk.gdk.threads_leave()

    def sync_message2(self, bus, message):
        if message.structure is None:
            return
        gtk.gdk.threads_enter()
        message_name = message.structure.get_name()
        if message_name == "prepare-xwindow-id":
            imagesink = message.src
            imagesink.set_property("force-aspect-ratio", True)
            imagesink.set_xwindow_id(self.webcamarea2.window.xid)
        gtk.gdk.threads_leave()


# MAIN
if __name__ == "__main__":
    gobject.threads_init()
    gtk.gdk.threads_init()
    mygui = H4GtkGui()
    gtk.settings_get_default().props.gtk_button_images = True
    gtk.main()



