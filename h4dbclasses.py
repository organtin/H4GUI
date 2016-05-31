import mysql.connector
from collections import OrderedDict
from copy import copy,deepcopy
import getpass

class DbInterface:
    
    cnx = None
    cursor = None

    myfile = open('cmsdaq_mysql.passwd','r')
    passwd = myfile.readline().replace('\n','')
    config = {
        'user': 'cmsdaq',
        'password': passwd,
#        'password': getpass.getpass('DB password: '),
        'host': 'pcethtb3.cern.ch',
#        'host': 'localhost',
        'database': 'rundb_v2',
        'raise_on_warnings': True,
        'autocommit': True
        }

    def __init__(self):
        while True:
            try:
                self.cnx = mysql.connector.connect(**self.config)
                break
            except mysql.connector.Error as err:
                if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
                    print 'Wrong password'
                    self.config['password']=getpass.getpass('DB password: ')
                else:
                    print err
        self.cursor = self.cnx.cursor()

    def __del__(self):
        self.cursor.close()
        self.cnx.close()

    def find(self,ptr,table,ignore_id=True):
        idkey=ptr.keys()[0]
        mykeys=ptr.keys()
        if ignore_id:
            mykeys=mykeys[1:]
        query='SELECT %s FROM %s WHERE ' %(idkey,table,)
        for key in mykeys:
            if not key==mykeys[0]:
                query+=' AND '
            thisval=ptr[key]
            if (thisval==None or thisval=='NULL'):
                query+=str().join(["%s"%key," IS NULL"])
            else:
                query+=str().join(["%s"%key,"='%s'"%thisval])
        self.cursor.execute(query)
        res=[]
        for line in self.cursor:
            res.append(int(line[0]))
        if len(res)>1:
            print 'Warning! More than one match, returning the last one.'
        if len(res)==0:
            return -1
        else:
            return res[-1]

    def read(self,ptr,table,args=''):
        memberlist=str(',').join(ptr.keys())
        query='SELECT %s FROM %s' % (memberlist,table,)
        args=args.replace('=None','=NULL')
        if not args=='':
            query+=' %s' % (args,)
        self.cursor.execute(query)
        res=[]
        for line in self.cursor: # line = (...,...,...)
            thisdict=ptr.__class__()
            for i in xrange(len(line)):
                thisdict[ptr.keys()[i]]=line[i]
            res.append(thisdict)
        return res

    def insert(self,dbclass,table):
        query='INSERT INTO %s (%s) VALUES ' % (table,','.join(dbclass.keys()),)
        vals=''
        for key in dbclass.keys():
            if vals=='':
                vals+='( '
            else:
                vals+=', '
            if dbclass[key]==None or dbclass[key]=='':
                vals+='NULL'
            else:
                vals+=str().join(["%(",str(key),")s"])
        vals+=')'
        query+=vals
#        print query%dbclass
        self.cursor.execute(query,dbclass)

    def update(self,dbclass,table,selection):
        query='UPDATE %s SET ' % (table,)
        for key in dbclass.keys():
            if not key==dbclass.keys()[0]:
                query+=','
            if dbclass[key]==None or dbclass[key]=='':
                query+=str().join([str(key),"=NULL"])
            else:
                query+=str().join([str(key),"=%(",str(key),")s"])
        selection=selection.replace('=None','=NULL')
        query+=' %s' % (selection,)
#        print query%dbclass
        self.cursor.execute(query,dbclass)


class AbsDbClass(OrderedDict):
    def __init__(self,doublelist):
        super(AbsDbClass,self).__init__()
        self.types={}
        for key,mytype in doublelist:
            self[key]=None
            self.types[key]=mytype
    def fixdatatypes(self):
        for key in self.keys():
            if not self[key]==None:
                thistype=None
                if self.types[key]=='int':
                    thistype=int
                elif self.types[key]=='float':
                    thistype=float
                else:
                    thistype=str
                if thistype and self[key]:
                    self[key]=thistype(self[key])
    def alltostring(self):
        for key in self.keys():
            if self[key]:
                self[key]=str(self[key])
    def show(self):
        showing=[]
        for key in self.keys():
            showing.append((key,self[key],self.types[key]))
        print showing

class RunDbClass(AbsDbClass):
    def __init__(self):
        super(RunDbClass,self).__init__([
                ('run_number','int'),
                ('run_type_id','int'),
                ('run_beam_id','int'),
                ('run_daq_id','int'),
                ('run_nevents','int'),
                ('run_deadtime','float'),
                ('table_horizontal_position','float'),
                ('table_vertical_position','float'),
                ('run_start_user_comment','str'),
                ('run_end_user_comment','str'),
                ('run_comment','str'),
                ('run_exit_code','int')
                ])
class RunTypeDbClass(AbsDbClass):
    def __init__(self):
        super(RunTypeDbClass,self).__init__([
                ('run_type_id','int'),
                ('run_type_description','str'),
                ('ped_frequency','int')
                ])
class BeamConfDbClass(AbsDbClass):
    def __init__(self):
        super(BeamConfDbClass,self).__init__([
                ('beam_conf_id','int'),
                ('beam_particle','str'),
                ('beam_energy','float'),
                ('beam_intensity','float'),
                ('beam_horizontal_width','float'),
                ('beam_vertical_width','float'),
                ('beam_horizontal_tilt','float'),
                ('beam_vertical_tilt','float')
                ])
class DaqConfDbClass(AbsDbClass):
    def __init__(self):
        super(DaqConfDbClass,self).__init__([
                ('daq_conf_id','int'),
                ('daq_type_description','str'),
                ('daq_gitcommitid','str')
                ])
class EnvironmentDbClass(AbsDbClass):
    def __init__(self):
        super(EnvironmentDbClass,self).__init__([
                ('env_readout_id','int'),
                ('env_timestamp','str'),
                ('T1','float'),
                ('T2','float'),
                ('T3','float'),
                ('T4','float'),
                ('T5','float'),
                ('Humidity','float'),
                ('DewPoint','float')
                ])
class ChillerDbClass(AbsDbClass):
    def __init__(self):
        super(ChillerDbClass,self).__init__([
                ('chil_readout_id','int'),
                ('chil_timestamp','str'),
                ('chil_treq','float'),
                ('chil_tset','float'),
                ('chil_tmon','float')
                ])
        
class DataTakingConfig:
    def __init__(self,other):
        self.r=other.r
        self.t=other.t
        self.b=other.b
        self.d=other.d
    def __init__(self):
        self.r=RunDbClass()
        self.t=RunTypeDbClass()
        self.b=BeamConfDbClass()
        self.d=DaqConfDbClass()
        self.run_updateable=['run_nevents','run_deadtime',
                             'run_start_user_comment','run_end_user_comment',
                             'run_comment','run_exit_code']
    def fixdatatypes(self):
        for item in [self.r,self.t,self.b,self.d]:
            item.fixdatatypes()
    def alltostring(self):
        for item in [self.r,self.t,self.b,self.d]:
            item.alltostring()

    def show(self):
        for item in [self.r,self.t,self.b,self.d]:
            item.show()
    

class DataTakingConfigHandler:

    def __init__(self,other):
        self.db=other.db

    def __init__(self):
        self.db=DbInterface()

    def add_into_db(self,thisconf):
        thisconf.r['run_number']=None
        thisconf.r['run_exit_code']=None
        runtypeid=self.db.find(thisconf.t,'run_type',ignore_id=True)
        if runtypeid<0:
            thisconf.t['run_type_id']=None
            self.db.insert(thisconf.t,'run_type')
            runtypeid=self.db.find(thisconf.t,'run_type',ignore_id=True)
        beamconfid=self.db.find(thisconf.b,'beam_configuration',ignore_id=True)
        if beamconfid<0:
            thisconf.b['beam_conf_id']=None
            self.db.insert(thisconf.b,'beam_configuration')
            beamconfid=self.db.find(thisconf.b,'beam_configuration',ignore_id=True)
        daqconfid=self.db.find(thisconf.d,'daq_configuration',ignore_id=True)
        if daqconfid<0:
            thisconf.d['daq_conf_id']=None
            self.db.insert(thisconf.d,'daq_configuration')
            daqconfid=self.db.find(thisconf.d,'daq_configuration',ignore_id=True)
        thisconf.r['run_type_id']=runtypeid
        thisconf.r['run_beam_id']=beamconfid
        thisconf.r['run_daq_id']=daqconfid
        self.db.insert(thisconf.r,'run')
        self.db.cursor.execute('SELECT LAST_INSERT_ID()')
        for line in self.db.cursor:
            thisrunnr=int(line[0])
#        print 'last insert id = ',thisrunnr
        thisconf=self.read_from_db(runnr=thisrunnr)
        return thisconf

    def getfirstsafe(self,obj):
        if len(obj)>0:
            return obj[0]
        else:
            return None

    def read_from_db(self,runnr):
        target=DataTakingConfig()
        myrunnr=runnr
        if not runnr:
            myrunnr=0
        target.r=self.getfirstsafe(self.db.read(target.r,'run','where run_number=%d'%myrunnr)) or RunDbClass()
        target.t=self.getfirstsafe(self.db.read(target.t,'run_type','where run_type_id=%d'%target.r['run_type_id'])) if target.r['run_type_id'] else RunTypeDbClass()
        target.b=self.getfirstsafe(self.db.read(target.b,'beam_configuration','where beam_conf_id=%d'%target.r['run_beam_id'])) if target.r['run_beam_id'] else BeamConfDbClass()
        target.d=self.getfirstsafe(self.db.read(target.d,'daq_configuration','where daq_conf_id=%d'%target.r['run_daq_id'])) if target.r['run_daq_id'] else DaqConfDbClass()
        target.fixdatatypes()
        return target

    def update_to_db(self,thisconf,onlycomment=False):
        oldconf=self.read_from_db(runnr=thisconf.r['run_number'])
        for word in thisconf.run_updateable:
            if onlycomment and not word=='run_comment':
                continue
            oldconf.r[word]=thisconf.r[word]
        oldconf.alltostring()
        self.db.update(oldconf.r,'run','where run_number=%s'%oldconf.r['run_number'])
        thisconf=self.read_from_db(runnr=thisconf.r['run_number'])
        return thisconf

    def get_highest_run_number(self):
        self.db.cursor.execute('SELECT MAX(run_number) FROM run;')
        res=0
        for line in self.db.cursor:
            if len(line)>0 and line[0]:
                res=int(line[0])
        return res

    def run_exists(self,runnr):
        self.db.cursor.execute('SELECT run_number FROM run WHERE run_number=%s',(str(int(runnr)),))
        res = False
        for line in self.db.cursor:
            if len(line)>0 and line[0] and int(line[0])==runnr:
                res=True
        return res

    def get_latest_environment(self):
        target=EnvironmentDbClass()
        target=self.getfirstsafe(self.db.read(target,'Environment','order by env_readout_id desc limit 1')) or EnvironmentDbClass()
        target.fixdatatypes()
        return target

    def get_latest_chillerreading(self):
        target=ChillerDbClass()
        target=self.getfirstsafe(self.db.read(target,'Chiller','order by chil_readout_id desc limit 1')) or ChillerDbClass()
        target.fixdatatypes()
        return target
