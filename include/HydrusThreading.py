import bisect
import collections
import HydrusExceptions
import Queue
import threading
import time
import traceback
import HydrusData
import HydrusGlobals as HG
import os

THREADS_TO_THREAD_INFO = {}
THREAD_INFO_LOCK = threading.Lock()

def GetThreadInfo( thread = None ):
    
    if thread is None:
        
        thread = threading.current_thread()
        
    
    with THREAD_INFO_LOCK:
        
        if thread not in THREADS_TO_THREAD_INFO:
            
            thread_info = {}
            
            thread_info[ 'shutting_down' ] = False
            
            THREADS_TO_THREAD_INFO[ thread ] = thread_info
            
        
        return THREADS_TO_THREAD_INFO[ thread ]
        
    
def IsThreadShuttingDown():
    
    if HG.view_shutdown:
        
        return True
        
    
    thread_info = GetThreadInfo()
    
    return thread_info[ 'shutting_down' ]
    
def ShutdownThread( thread ):
    
    thread_info = GetThreadInfo( thread )
    
    thread_info[ 'shutting_down' ] = True
    
class DAEMON( threading.Thread ):
    
    def __init__( self, controller, name ):
        
        threading.Thread.__init__( self, name = name )
        
        self._controller = controller
        self._name = name
        
        self._event = threading.Event()
        
        self._controller.sub( self, 'wake', 'wake_daemons' )
        self._controller.sub( self, 'shutdown', 'shutdown' )
        
    
    def _DoPreCall( self ):
        
        if HG.daemon_report_mode:
            
            HydrusData.ShowText( self._name + ' doing a job.' )
            
        
    
    def shutdown( self ):
        
        ShutdownThread( self )
        
        self.wake()
        
    
    def wake( self ):
        
        self._event.set()
        
    
class DAEMONWorker( DAEMON ):
    
    def __init__( self, controller, name, callable, topics = None, period = 3600, init_wait = 3, pre_call_wait = 0 ):
        
        if topics is None:
            
            topics = []
            
        
        DAEMON.__init__( self, controller, name )
        
        self._callable = callable
        self._topics = topics
        self._period = period
        self._init_wait = init_wait
        self._pre_call_wait = pre_call_wait
        
        for topic in topics:
            
            self._controller.sub( self, 'set', topic )
            
        
        self.start()
        
    
    def _CanStart( self, time_started_waiting ):
        
        return self._PreCallWaitIsDone( time_started_waiting ) and self._ControllerIsOKWithIt()
        
    
    def _ControllerIsOKWithIt( self ):
        
        return True
        
    
    def _PreCallWaitIsDone( self, time_started_waiting ):
        
        # just shave a bit off so things that don't have any wait won't somehow have to wait a single accidentaly cycle
        time_to_start = ( float( time_started_waiting ) - 0.1 ) + self._pre_call_wait
        
        return HydrusData.TimeHasPassed( time_to_start )
        
    
    def run( self ):
        
        self._event.wait( self._init_wait )
        
        while True:
            
            if IsThreadShuttingDown():
                
                return
                
            
            time_started_waiting = HydrusData.GetNow()
            
            while not self._CanStart( time_started_waiting ):
                
                time.sleep( 1 )
                
                if IsThreadShuttingDown():
                    
                    return
                    
                
            
            self._DoPreCall()
            
            try:
                
                self._callable( self._controller )
                
            except HydrusExceptions.ShutdownException:
                
                return
                
            except Exception as e:
                
                HydrusData.ShowText( 'Daemon ' + self._name + ' encountered an exception:' )
                
                HydrusData.ShowException( e )
                
            
            if IsThreadShuttingDown(): return
            
            self._event.wait( self._period )
            
            self._event.clear()
            
        
    
    def set( self, *args, **kwargs ): self._event.set()
    
# Big stuff like DB maintenance that we don't want to run while other important stuff is going on, like user interaction or vidya on another process
class DAEMONBackgroundWorker( DAEMONWorker ):
    
    def _ControllerIsOKWithIt( self ):
        
        return self._controller.GoodTimeToDoBackgroundWork()
        
    
# Big stuff that we want to run when the user sees, but not at the expense of something else, like laggy session load
class DAEMONForegroundWorker( DAEMONWorker ):
    
    def _ControllerIsOKWithIt( self ):
        
        return self._controller.GoodTimeToDoForegroundWork()
        
    
class THREADCallToThread( DAEMON ):
    
    def __init__( self, controller, name ):
        
        DAEMON.__init__( self, controller, name )
        
        self._queue = Queue.Queue()
        
        self._currently_working = True # start off true so new threads aren't used twice by two quick successive calls
        
    
    def CurrentlyWorking( self ):
        
        return self._currently_working
        
    
    def put( self, callable, *args, **kwargs ):
        
        self._currently_working = True
        
        self._queue.put( ( callable, args, kwargs ) )
        
        self._event.set()
        
    
    def run( self ):
        
        while True:
            
            try:
                
                while self._queue.empty():
                    
                    if self._controller.ModelIsShutdown():
                        
                        return
                        
                    
                    self._event.wait( 1200 )
                    
                    self._event.clear()
                    
                
                self._DoPreCall()
                
                ( callable, args, kwargs ) = self._queue.get()
                
                callable( *args, **kwargs )
                
                del callable
                
            except HydrusExceptions.ShutdownException:
                
                return
                
            except Exception as e:
                
                HydrusData.Print( traceback.format_exc() )
                
                HydrusData.ShowException( e )
                
            finally:
                
                self._currently_working = False
                
            
            time.sleep( 0.00001 )
            
        
    
class JobScheduler( threading.Thread ):
    
    def __init__( self, controller ):
        
        threading.Thread.__init__( self, name = 'Job Scheduler' )
        
        self._controller = controller
        
        self._waiting = []
        
        self._waiting_lock = threading.Lock()
        
        self._new_job_arrived = threading.Event()
        
        self._cancel_filter_needed = threading.Event()
        self._sort_needed = threading.Event()
        
        self._controller.sub( self, 'shutdown', 'shutdown' )
        
    
    def _FilterCancelled( self ):
        
        with self._waiting_lock:
            
            self._waiting = [ job for job in self._waiting if not job.IsCancelled() ]
            
        
    
    def _GetLoopWaitTime( self ):
        
        with self._waiting_lock:
            
            if len( self._waiting ) == 0:
                
                return 0.2
                
            
            next_job = self._waiting[0]
            
        
        time_delta_until_due = next_job.GetTimeDeltaUntilDue()
        
        return min( 1.0, time_delta_until_due )
        
    
    def _NoWorkToStart( self ):
        
        with self._waiting_lock:
            
            if len( self._waiting ) == 0:
                
                return True
                
            
            next_job = self._waiting[0]
            
        
        if next_job.IsDue():
            
            return False
            
        else:
            
            return True
            
        
    
    def _SortWaiting( self ):
        
        # sort the waiting jobs in ascending order of expected work time
        
        with self._waiting_lock: # this uses __lt__ to sort
            
            self._waiting.sort()
            
        
    
    def _StartWork( self ):
        
        while True:
            
            with self._waiting_lock:
                
                if len( self._waiting ) == 0:
                    
                    break
                    
                
                next_job = self._waiting[0]
                
                if next_job.IsDue():
                    
                    next_job = self._waiting.pop( 0 )
                    
                    next_job.StartWork()
                    
                else:
                    
                    break # all the rest in the queue are not due
                    
                
            
        
    
    def AddJob( self, job ):
        
        with self._waiting_lock:
            
            bisect.insort( self._waiting, job )
            
        
        self._new_job_arrived.set()
        
    
    def JobCancelled( self ):
        
        self._cancel_filter_needed.set()
        
    
    def shutdown( self ):
        
        ShutdownThread( self )
        
    
    def WorkTimesHaveChanged( self ):
        
        self._sort_needed.set()
        
    
    def run( self ):
        
        while True:
            
            try:
                
                while self._NoWorkToStart():
                    
                    if self._controller.ModelIsShutdown():
                        
                        return
                        
                    
                    #
                    
                    if self._cancel_filter_needed.is_set():
                        
                        self._FilterCancelled()
                        
                        self._cancel_filter_needed.clear()
                        
                    
                    if self._sort_needed.is_set():
                        
                        self._SortWaiting()
                        
                        self._sort_needed.clear()
                        
                        continue # if some work is now due, let's do it!
                        
                    
                    #
                    
                    wait_time = self._GetLoopWaitTime()
                    
                    self._new_job_arrived.wait( wait_time )
                    
                    self._new_job_arrived.clear()
                    
                
                self._StartWork()
                
            except HydrusExceptions.ShutdownException:
                
                return
                
            except Exception as e:
                
                HydrusData.Print( traceback.format_exc() )
                
                HydrusData.ShowException( e )
                
            
            time.sleep( 0.00001 )
            
        
    
class SchedulableJob( object ):
    
    def __init__( self, controller, scheduler, work_callable, initial_delay = 0.0 ):
        
        self._controller = controller
        self._scheduler = scheduler
        self._work_callable = work_callable
        
        self._next_work_time = HydrusData.GetNowFloat() + initial_delay
        
        self._work_lock = threading.Lock()
        
        self._currently_working = threading.Event()
        self._is_cancelled = threading.Event()
        
    
    def __lt__( self, other ): # for the scheduler to do bisect.insort noice
        
        return self._next_work_time < other._next_work_time
        
    
    def __repr__( self ):
        
        return 'Schedulable Job: ' + repr( self._work_callable )
        
    
    def _BootWorker( self ):
        
        self._controller.CallToThread( self.Work )
        
    
    def Cancel( self ):
        
        self._is_cancelled.set()
        
        self._scheduler.JobCancelled()
        
    
    def CurrentlyWorking( self ):
        
        return self._currently_working.is_set()
        
    
    def GetTimeDeltaUntilDue( self ):
        
        return HydrusData.GetTimeDeltaUntilTimeFloat( self._next_work_time )
        
    
    def IsCancelled( self ):
        
        return self._is_cancelled.is_set()
        
    
    def IsDue( self ):
        
        return HydrusData.TimeHasPassedFloat( self._next_work_time )
        
    
    def MoveNextWorkTimeToNow( self ):
        
        self._next_work_time = HydrusData.GetNowFloat()
        
        self._scheduler.WorkTimesHaveChanged()
        
    
    def StartWork( self ):
        
        if self._is_cancelled.is_set():
            
            return
            
        
        self._currently_working.set()
        
        self._BootWorker()
        
    
    def Work( self ):
        
        try:
            
            with self._work_lock:
                
                self._work_callable()
                
            
        finally:
            
            self._currently_working.clear()
            
        
    
class RepeatingJob( SchedulableJob ):
    
    def __init__( self, controller, scheduler, work_callable, period, initial_delay = 0.0 ):
        
        SchedulableJob.__init__( self, controller, scheduler, work_callable, initial_delay = initial_delay )
        
        self._period = period
        
        self._stop_repeating = threading.Event()
        
    
    def Cancel( self ):
        
        SchedulableJob.Cancel( self )
        
        self._stop_repeating.set()
        
    
    def Delay( self, delay ):
        
        self._next_work_time = HydrusData.GetNowFloat() + delay
        
        self._scheduler.WorkTimesHaveChanged()
        
    
    def IsFinishedWorking( self ):
        
        return self._stop_repeating.is_set()
        
    
    def SetPeriod( self, period ):
        
        self._period = period
        
    
    def StartWork( self ):
        
        if self._stop_repeating.is_set():
            
            return
            
        
        SchedulableJob.StartWork( self )
        
    
    def Work( self ):
        
        SchedulableJob.Work( self )
        
        if not self._stop_repeating.is_set():
            
            self._next_work_time = HydrusData.GetNowFloat() + self._period
            
            self._scheduler.AddJob( self )
            
        
    
