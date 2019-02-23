'''
Instantiate an Actifio object to perform operations on an Actifio appliance.

'''

import urllib3
import sys
import json
from functools import wraps

# import auxialary libraries 
if sys.version [:3] == "2.7":
  from actexceptions import *
  from ActSupportClasses import ActHost, ActHostCollection, ActApplication, ActAppCollection, ActImage, ActImageCollection, ActJob, ActJobsCollection
elif sys.version[0] == "3":
  from Actifio.actexceptions import *
  from Actifio.ActSupportClasses import ActHost, ActHostCollection, ActApplication, ActAppCollection, ActImage, ActImageCollection, ActJob, ActJobsCollection

# Import urlencode for the correct version
if sys.version [:3] == "2.7":
  from urllib import quote_plus as urlencode_str
  from urllib import urlencode as urlencode
elif sys.version[0] == "3":
  # NOTE: Not sure which version supports this. Working with 3.5, so limiting support to 3.5+, 
  # this is a temporary measure.
  if int(sys.version[2]) > 4: 
    from urllib.parse import quote_plus as urlencode_str
    from urllib.parse import urlencode as urlencode

# We do support self signed certs... and need to suppress unwanted chatter
urllib3.disable_warnings() 

__all__ = ['Actifio']

class ActEnforce():
  @classmethod
  def needs_token(cls,act_func):
    @wraps(act_func)
    def decorated(cls, *args, **kwargs):
      if Actifio._sessionid[cls.appliance][cls.username] == '':
        try:
          Actifio._create_session(cls)
        except:
          raise
      try:
        result = act_func(cls,*args, **kwargs)
      except:
        try:
          if not Actifio._validate_token(cls):
            try:
              print ("creating session id")
              Actifio._create_session(cls)
            except:
              raise
            try:
              result = act_func(cls,*args, **kwargs)
            except:
              print(act_func.__name__ + "failed")
              raise
            else:
              return result
          else:
            raise
        except:
          raise
      else:
        return result
    return decorated


class Actifio:
  """
  Actifio instance:

  appliance: IP or FQDN of the appliance
  username: Username to login to the appliance
  password: Password

  """
  _sessionid = {}
  
  def __init__ (self, appliance, username, password, cert_validation=False):
    """
    Actifio instance:

    appliance: IP or FQDN of the appliance
    username: Username to login to the appliance
    password: Password

    """
    # vendor key is fixed
    vendorkey = "195B-4370-2506-0A60-1F41-5829-067B-603C-6737-1244-0A11-6742-0745-4023-1A"
    # functools need a __name__ for the wraps
    self.__name__ = "Actifio"
    # compose the URI for the API
    self._apiBase = "/actifio/api"
    self.appliance = appliance
    self.username = username
    #sessionid is unique per user in an appliance
    Actifio._sessionid.update( { appliance: {} } )
    Actifio._sessionid[appliance].update( { username: ''} )
    # compose the login params
    self._loginParams = "/login?name=" + username 
    self._loginParams += "&password=" + password
    self._loginParams += "&vendorkey=" + vendorkey

    self._loginURI = self._apiBase + self._loginParams
    self._infoURI = self._apiBase + "/info/"
    self._taskURI = self._apiBase + "/task/"
    self._sargURI = self._apiBase + "/report/"

    # create the https poolmanager
    cert_str = 'CERT_REQUIRED' if cert_validation else 'CERT_NONE'

    self._httppool = urllib3.HTTPSConnectionPool (host=appliance, port=443, cert_reqs=cert_str)

  def __str__(self):
    if Actifio._sessionid[self.appliance][self.username] == "":
      return "Connection not verified; Appliance: " + str(self.appliance) + "; Username: " + str(self.username)
    else:
      return "Connection verified (session id): " + str(Actifio._sessionid[self.appliance][self.username]) + "; Appliance: " + str(self.appliance) + "; Username: " + str(self.username)

  @staticmethod
  def _validate_token (self):
    """
    Validate the exisiting _sessionid token. Return True if the token is valid.
    """
    
    if Actifio._sessionid[self.appliance][self.username] == '' :
      return False
    try:
      resp = self._httppool.request (
        'GET',
        self._infoURI + 'lsversion?sessionid=' + Actifio._sessionid[self.appliance][self.username]
      )
    except Exception:
      raise ActConnectError("Unable to reach the appliance: check the IP address / hostname")
    else:
      if resp.status != 200:
        return False
      else:
        return True


  @staticmethod
  def _create_session (self):
    """
    Create a new session taken 
    """
    try:
      login = self._httppool.request (
        'GET',
        self._loginURI
      )
    except Exception as e:
      raise ActConnectError("Unable to reach the appliance: check the IP address / hostname")
    else:
      try:    
        response = json.loads(login.data)
      except:
        raise ActLoginError("This does not seem to be a Actifio Sky/CDS appliance")
      if login.status == 200:
        try:
          Actifio._sessionid[self.appliance][self.username] = response['sessionid']
        except:
          raise ActLoginError(response['errormessage'])
      else:
        raise ActLoginError("This does not seem to be a Actifio Sky/CDS appliance")



  @ActEnforce.needs_token
  def run_uds_command(self, cmdType, 
    cmdUDS, 
    cmdArgs={}):
    """
    Wrapper function to convert CLI commands to the rest API.
      cmdType: info / task 
      cmdUDS: Command to use (eg. lsuser, lshost, mkapplication... etc.)
      cmdArgs: Dictionary with arguments to the command
               For example: 
               vmdiscovery -discovercluster -host 1234 
               { 'discovercluster': None, 'host': 1234 }

               lsapplication -filtervalues "appname=mydb&hostname=myhost"
               { 'filtervalues': { 'appname': 'mydb', 'hostname': 'myhost' } }

               lshost 123
               { 'argument': 123 }

               RESTfulAPI_*.pdf would be good referecne point for the __SIMILARITY__ and 
               __PATTERN__.
    """

    _URI = self._infoURI if cmdType == "info" else self._taskURI

    # append the command to URI
    _URI += cmdUDS + '?'

    # provision for the non-equal opprations
    def __regex_args (key, value):
      import re
      not_equal = re.compile(r'^not\s+(.*)')
      greater_than = re.compile(r'^\>\s*(.*)')
      smaler_than = re.compile(r'^\<\s*(.*)')
      
      ne_match = not_equal.search(value)
      gt_match = greater_than.search(value)
      st_match = smaler_than.search(value)

      if ne_match is not None:
        return key + "!=" + ne_match.group(1)
      elif st_match is not None:
        return key + "<" + st_match.group(1)
      elif gt_match is not None:
        return key + ">" + gt_match.group(1)
      else:
        return key + "=" + value

    # append the argument
    for key in cmdArgs:
      if type(cmdArgs[key]) == dict:
        # Actifio API expects this to be urlencoded
        _URI += key + '=' + urlencode_str('&'.join([ __regex_args(filter_key, cmdArgs[key][filter_key]) for filter_key in cmdArgs[key]])) + '&'
      elif cmdArgs[key] == None:
        _URI += urlencode_str(key) + '&'
      else:
        _URI += urlencode_str(key) + '=' + urlencode_str(str(cmdArgs[key])) + '&'
        
    _URI += 'sessionid=' + Actifio._sessionid[self.appliance][self.username]
    try:
      udsout = self._httppool.request (
        'GET' if cmdType == 'info' else 'POST',
        _URI
      )
      # print(_URI) 
    except Exception as e:
      print (e)
      raise ActConnectError("Failed to connect the appliance")
    else:
      response = json.loads(udsout.data)
      if udsout.status != 200:
        self._lastout = ''
        raise ActAPIError(response['errormessage'])
      else:
        self._lastout = response
        return self._lastout


  @ActEnforce.needs_token
  def run_sarg_command(self, cmdSARG, cmdArgs):
    """
    Wrapper function to convert CLI commands to the rest API. 
      cmdSARG: Command to use (eg. reportsnaps, reportapps... etc.)
      cmdArgs: Dictionary with arguments to the command
               For example: 
               reportapps -a 1234 -x
               { 'a': 1234, 'x': None }
    """

    _URI = self._sargURI

    # append the command to URI
    _URI += cmdSARG + '?'

    # append the argument
    for key in cmdArgs:
      if type(cmdArgs[key]) == dict:
        # Actifio API expects this to be urlencoded
        _URI += key + '=' + urlencode_str('&'.join([ filter_key + '=' + cmdArgs[key][filter_key] for filter_key in cmdArgs[key]])) + '&'
      elif cmdArgs[key] == None:
        _URI += urlencode_str(key) + '&'
      else:
        _URI += urlencode_str(key) + '=' + urlencode_str(str(cmdArgs[key])) + '&'
        
    _URI += 'sessionid=' + Actifio._sessionid[self.appliance][self.username]
    try:
      sargout = self._httppool.request (
        'GET',
        _URI
      )
    except urllib3.exceptions.NewConnectionError:
      raise ActConnectError("Unable to make connection to the appliance")
    else:
      response = json.loads(sargout.data)
      if sargout.status != 200:
        self._lastout = ''
        raise ActAPIError(response['errormessage'])
      else:
        self._lastout = response
        return self._lastout

  
  # def define_iscsi_host(self, hostname, ipaddress, host_type='geenric', dsik_pref='BLOCK', detect_as_vm=False):
  #   #check whether the host entry exists
  #   try:
  #     lshost = self.run_uds_command('info', 'lshost',{ 'filtervalue': { 'hostname': hostname }})
  #   except:
  #     raise
  #   else:
  #     if len(lshost['result']) > 0:
  #       #found the host:
  #       host = lshost['result']
  #     else:
  #       self.run_uds_command('task','chhost',{ 'hostname': name})


  def get_hosts (self, **kwargs):
    '''
    Supported filter parameters are:

    *  alternateip
      IP address which is not the primary Ip address

    *  diskpref
      Valid options are: BLOCK / NFS

    *  friendlypath
      Friendly path of the host

    *  hasagent
      Hosts with agent istalled

    *  hostname
      Host name, as defined in Actifio

    *  hosttype
      Host type, accepted options:  generic | hmc | hpux | hyperv | isilon | netapp 7 mode | 
      netapp svm | openvms | tpgs | vcenter

    *  ipaddress
      IP dddress of the host name. This is the main IP. Check alternateip option for the alternate IP addresses.

    *  isvm
      If set to true, will retrun hosts defined as VMs.

    *  isesxhost
    *  isvcenterhost
    *  originalhostid
    *  osrelease
    *  osversion
    *  sourcecluster
    *  svcname
    *  uniquename
    *  vcenterhostid
    *  isclusterhost

    '''
    try:
      if len(kwargs) > 0:
        lshost_out = self.run_uds_command('info', 'lshost',{ 'filtervalue': kwargs })
      else:
        lshost_out = self.run_uds_command('info', 'lshost',{})
    except:
      raise
    else:
      return ActHostCollection (self, lshost_out['result'])



  def get_applications (self, **kwargs):
    '''
    Supported filter parameters are:

    *  appname
      Application name

    *  apptype
      Application Type

    *  appversion
    *  auxinfo
    *  description
    *  friendlytype
    *  hostid
      Source HostID

    *  hostname
      Source Hostname

    *  id
      Application ID

    *  ignore
    *  isclustered
    *  networkip
    *  networkname
    *  originalappid
    *  pathname
    *  protectable    [ NONE | FULLY | PARTIALLY ]
    *  sourcecluster

    '''
    try:
      if len(kwargs) > 0:
        lsapplication_out = self.run_uds_command('info', 'lsapplication',{ 'filtervalue': kwargs })
      else:
        lsapplication_out = self.run_uds_command('info', 'lsapplication',{ })
    except:
      raise
    else:
      return ActAppCollection (self, lsapplication_out['result'])


  def get_images(self, **kwargs):
    '''
    Supported filtervalues are:

    *  appid
      Application ID

    *  appname
      Application Name

    *  apptype
      Application type

    *  backupname
      Image Name

    *  characteristic    [ PRIMARY | MOUNT | UNMOUNT ]
    *  consistencydate
      Backup consistency date

    *  expiration
    *  hostid
    *  hostname
      Source Hostname

    *  jobclass          [ snapshot | dedup | dedupasync | liveclone | syncback ]
    *  label
      Backu label

    *  mappedhost
    *  mountedhost
    *  policyname
    *  prepdate
    *  slpname
    *  sltname
    *  sourceimage
    *  sourceuds
    *  targetuds
    *  virtualsize

    '''

    try:
      if len(kwargs) > 0:
        lsbackup_out = self.run_uds_command('info', 'lsbackup',{ 'filtervalue': kwargs })
      else:
        lsbackup_out = self.run_uds_command('info', 'lsbackup',{ })
    except:
      raise
    else:
      return ActImageCollection(self, lsbackup_out['result'])


  def get_image_bytime(self, ActAppObject, restoretime, strict_policy=False, job_class="snapshot"):
    """
    This method return a ActImage object with a single imaage to the specified restore time.

      ActAppObject: should be the application in the form of ActApplication object.
      strict_policy: [True | False] If set to true, the image will be selected from log recovery range, with                  the closest image to replay the logs on.  
      restoretime: can be datetime obect or string with the format [YYYY-MM-DD HH:mm:ss]
      job_class: Defaults to snapshot. Should be string type, to any supported image jobclass.
    """
    from datetime import datetime
    timeformat = "%Y-%m-%d %H:%M:%S"

    try:
      if isinstance(restoretime, str):
        if restoretime != "":
          try:
            restore_time = datetime.strptime(restoretime, timeformat)
          except:
            raise ActUserError("'restoretime' need to be in the format of [YYYY-MM-DD HH:mm:ss]")
      elif isinstance(restoretime, datetime):
        restore_time = restoretime
      else:
        raise ActUserError("'restoretime' should be in the type of datetime or string with format of [YYYY-MM-DD HH:mm:ss]")
    except KeyError:
      restoretime = ""

    if strict_policy:
      try:
        logsmart_images = self.get_images(appid=ActAppObject.id, componenttype="1")
      except:
        raise

      if len(logsmart_images) == 0:
        raise ActUserError("'strict_policy=True' is only valid for LogSmart enables applications. This application is not LogSmart enabled.")
      else:
        ls_image = logsmart_images[0]
        ls_image.details()
        try:
          viable_images = self.get_images(appid=ActAppObject.id, consistencydate=">" + ls_image.beginpit, jobclass=job_class)
        except:
          raise
      
      prefered_image = None
      prefered_image_time = None

      for img in viable_images:
        try:
          consistency_time = datetime.strptime(img.consistencydate[:-4], timeformat)
        except:
          raise
        if prefered_image is None:
          if consistency_time < restore_time:
            prefered_image = img
            prefered_image_time = consistency_time
        else:
          if prefered_image_time < consistency_time < restore_time:
            prefered_image = img
            prefered_image_time = consistency_time
      
      return prefered_image
    else:
      try:
        app_images = self.get_images(appid=ActAppObject.id, jobclass=job_class)
      except:
        raise

      shortest_gap = None
      prefered_image = None
      prefered_image_time = None

      for img in app_images:
        try:
          consistency_time = datetime.strptime(img.consistencydate[:-4], timeformat)
        except:
          raise
        
        if prefered_image is None:
          # print("processing first image")
          prefered_image = img
          prefered_image_time = consistency_time
          # print( str(consistency_time)+ "  -  " + str(restore_time))
          if consistency_time > restore_time:
            # print( "consistency time is later than restore time")
            shortest_gap = consistency_time - restore_time
          else:
            shortest_gap = restore_time - consistency_time
            # print( "restore time is later than consistency ")
        else:
          # print("first image is already set")
          # print( str(consistency_time)+ "  -  " + str(prefered_image_time))
          if consistency_time > restore_time:
            # print( "consistency time is later than prefered image time")
            this_image_gap = consistency_time - restore_time
          else:
            # print( "prefered image time is later than consistency ")
            this_image_gap = restore_time - consistency_time

          if shortest_gap.total_seconds() > this_image_gap.total_seconds():
            # print("prefered image time is :" + str(consistency_time))
            prefered_image = img
            prefered_image_time = consistency_time
            shortest_gap = this_image_gap

      return prefered_image


  def get_jobs(self, **kwargs):
    '''
    Supported filtervalues are:

   *  appid
   *  appname
   *  component
   *  enddate
   *  errorcode
   *  expirationdate
   *  hostname
   *  isscheduled       [ true | false ]
   *  jobclass          
   *  jobname
   *  jobtag
   *  parentid
   *  policyname
   *  priority
   *  progress
   *  queuedate
   *  relativesize
   *  retrycount
   *  sltname
   *  startdate
   *  status            [ running | queued | paused | interrupted | stalled ]
   *  sourceid
   *  virtualsize

    '''
    try:
      lsjob_out = self.run_uds_command('info', 'lsjob',{ 'filtervalue': kwargs })
      lsjobhist_out = self.run_uds_command('info', 'lsjobhistory',{ 'filtervalue': kwargs })
    except:
      raise
    else:
      return ActJobsCollection (self, lsjob_out['result'] + lsjobhist_out['result'])


  def clone_database(self, source_hostname, source_appname, target_hostname, **kwargs):
    '''
    This method creates a virtual clone of Oracle or SQL server database.
      source_hostname: Hostname of the source host where the database was captured from
      source_appname: source application name, or the database name
      target_hostname: target host where the virtual clone need to be created on

      Oracle Related Parameters:
        oracle_home (required): ORACLE_HOME
        oracle_db_name (required): SID of the target clone
        oracle_tns_admin (optional): TNS admin path, defaults to $ORACLE_HOME/network/admin.
        oracle_db_mem (optional): Total Memory Target for the database, defaults to 512MB.
        oracle_sga_pct (optional): Memory Percentage to allocate for SGA
        oracle_redo_size (optional): Redo Log size in MB, defaults to 500
        oracle_shared_pool (optional): Oracle Shared Pool size
        oracle_db_cache_size (optional): Oracle DB Cache size
        oracle_recover_dest_size (optional): Oracle Parameter db_recover_dest_size. Defaults to 5000
        oracle_diagnostic_dest (optional): Oracle Diagnostic Destination
        oracle_nprocs (optional): Num of Max processes
        oracle_open_cursors (optional): Number of open_cursors. defaults to 1000 
        oracle_char_set (optional): Characterset. Defaults to 'AL32UTF8'
        oracle_tns_ip (optional): TNS IP Address
        oracle_tns_port (optional): TNS Port
        oracle_tns_domain (optional): TNS Domain
        oracle_no_nid (optional): Do not change the DBID of the new clone. Will maintain same DBID as the source. Defaults to FALSE
        oracle_no_tns_update (optional): Do not update TNS records. Defaults to FALSE
        oracle_restore_recov (optional): Recover the oracle database. Defaults to TRUE
        oracle_no_rac (optional): Treat as Oracle RAC. Defaults to TRUE

      SQLServer Related
        sql_instance_name (required): Target SQL Server instance name
        sql_recover_userlogins (optional): Recover user logins of the database. Defaults to FALSE
        sql_username (optional): Username for database provisioning
        sql_password (optional): Password for the specified user 
        
      SQLServer DB Application
        sql_db_name (reuired): Database name at the target instance. (Only required if the source application is database or single database mount from instance.) 

      SQLServer Instance 
        sql_source_dbnames (required): Source database names if the source application is SQL instance. Use ',' as delimiter for multiple databases. (Only required if the source application is SQL server instance.) 
        sql_cg_name (required): Consistency group name. (Only required if the source application is SQL Server instance and mount multiple databases at a time.)
        sql_dbname_prefix (optional): Prefix of database name for multiple database mount
        sql_dbname_suffix (optional): Suffix of database name for multiple database mount

    '''

    # Strict policy
    try:
      if isinstance(kwargs['strict_policy'], bool):
        strict_policy = kwargs['strict_policy']
      else:
        raise ActUserError("'strict_policy' should be boolean")
    except KeyError:
      strict_policy = False
    
    # restore time
    # from datetime import datetime
    # timeformat = "%Y-%m-%d %H:%M:%S"

    try:
      source_application = self.get_applications(appname=source_appname,hostname=source_hostname,apptype="not VMBackup")
    except Exception as e:
      raise

    if len(source_application) < 1:
      raise ActUserError("Unable to find the 'source_application' application: " + source_application)

    try:
      target_host = self.get_hosts(hostname=target_hostname)
    except ActAPIError as e:
      raise

