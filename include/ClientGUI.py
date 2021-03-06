import HydrusConstants as HC
import ClientConstants as CC
import ClientCaches
import ClientData
import ClientDragDrop
import ClientExporting
import ClientGUICommon
import ClientGUIDialogs
import ClientGUIDialogsManage
import ClientGUIFrames
import ClientGUIManagement
import ClientGUIMenus
import ClientGUIPages
import ClientGUIParsing
import ClientGUIPopupMessages
import ClientGUIScrolledPanelsEdit
import ClientGUIScrolledPanelsManagement
import ClientGUIScrolledPanelsReview
import ClientGUIShortcuts
import ClientGUITopLevelWindows
import ClientDownloading
import ClientMedia
import ClientNetworking
import ClientSearch
import ClientServices
import ClientThreading
import collections
import cv2
import gc
import hashlib
import HydrusData
import HydrusExceptions
import HydrusPaths
import HydrusGlobals as HG
import HydrusNetwork
import HydrusNetworking
import HydrusSerialisable
import HydrusTagArchive
import HydrusVideoHandling
import os
import PIL
import shlex
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import traceback
import types
import webbrowser
import wx
import wx.adv

ID_TIMER_GUI_BANDWIDTH = wx.NewId()
ID_TIMER_PAGE_UPDATE = wx.NewId()
ID_TIMER_UI_UPDATE = wx.NewId()
ID_TIMER_ANIMATION_UPDATE = wx.NewId()

# Sizer Flags

MENU_ORDER = [ 'file', 'undo', 'pages', 'database', 'pending', 'network', 'services', 'help' ]

class FrameGUI( ClientGUITopLevelWindows.FrameThatResizes ):
    
    def __init__( self, controller ):
        
        self._controller = controller
        
        title = self._controller.new_options.GetString( 'main_gui_title' )
        
        if title is None or title == '':
            
            title = 'hydrus client'
            
        
        ClientGUITopLevelWindows.FrameThatResizes.__init__( self, None, title, 'main_gui', float_on_parent = False )
        
        bandwidth_width = ClientData.ConvertTextToPixelWidth( self, 17 )
        idle_width = ClientData.ConvertTextToPixelWidth( self, 6 )
        system_busy_width = ClientData.ConvertTextToPixelWidth( self, 13 )
        db_width = ClientData.ConvertTextToPixelWidth( self, 14 )
        
        stb_style = wx.STB_SIZEGRIP | wx.STB_ELLIPSIZE_END | wx.FULL_REPAINT_ON_RESIZE
        
        self._statusbar = self.CreateStatusBar( 5, stb_style )
        self._statusbar.SetStatusWidths( [ -1, bandwidth_width, idle_width, system_busy_width, db_width ] )
        
        self._statusbar_thread_updater = ClientGUICommon.ThreadToGUIUpdater( self._statusbar, self.RefreshStatusBar )
        
        self._focus_holder = wx.Window( self, size = ( 0, 0 ) )
        
        self._closed_pages = []
        self._closed_page_keys = set()
        self._deleted_page_keys = set()
        self._lock = threading.Lock()
        
        self._notebook = ClientGUIPages.PagesNotebook( self, self._controller, 'top page notebook' )
        
        self.SetDropTarget( ClientDragDrop.FileDropTarget( self, self.ImportFiles, self.ImportURL, self._notebook.MediaDragAndDropDropped, self._notebook.PageDragAndDropDropped ) )
        
        wx.GetApp().SetTopWindow( self )
        
        self._message_manager = ClientGUIPopupMessages.PopupMessageManager( self )
        
        self.Bind( wx.EVT_LEFT_DCLICK, self.EventFrameNewPage )
        self.Bind( wx.EVT_MIDDLE_DOWN, self.EventFrameNewPage )
        self.Bind( wx.EVT_RIGHT_DOWN, self.EventFrameNotebookMenu )
        self.Bind( wx.EVT_CLOSE, self.EventClose )
        self.Bind( wx.EVT_SET_FOCUS, self.EventFocus )
        self.Bind( wx.EVT_CHAR_HOOK, self.EventCharHook )
        self.Bind( wx.EVT_TIMER, self.TIMEREventBandwidth, id = ID_TIMER_GUI_BANDWIDTH )
        self.Bind( wx.EVT_TIMER, self.TIMEREventPageUpdate, id = ID_TIMER_PAGE_UPDATE )
        self.Bind( wx.EVT_TIMER, self.TIMEREventUIUpdate, id = ID_TIMER_UI_UPDATE )
        self.Bind( wx.EVT_TIMER, self.TIMEREventAnimationUpdate, id = ID_TIMER_ANIMATION_UPDATE )
        
        self._controller.sub( self, 'AddModalMessage', 'modal_message' )
        self._controller.sub( self, 'DeleteOldClosedPages', 'delete_old_closed_pages' )
        self._controller.sub( self, 'NewPageImportHDD', 'new_hdd_import' )
        self._controller.sub( self, 'NewPageQuery', 'new_page_query' )
        self._controller.sub( self, 'NotifyClosedPage', 'notify_closed_page' )
        self._controller.sub( self, 'NotifyNewImportFolders', 'notify_new_import_folders' )
        self._controller.sub( self, 'NotifyNewOptions', 'notify_new_options' )
        self._controller.sub( self, 'NotifyNewPages', 'notify_new_pages' )
        self._controller.sub( self, 'NotifyNewPending', 'notify_new_pending' )
        self._controller.sub( self, 'NotifyNewPermissions', 'notify_new_permissions' )
        self._controller.sub( self, 'NotifyNewServices', 'notify_new_services_gui' )
        self._controller.sub( self, 'NotifyNewSessions', 'notify_new_sessions' )
        self._controller.sub( self, 'NotifyNewUndo', 'notify_new_undo' )
        self._controller.sub( self, 'PresentImportedFilesToPage', 'imported_files_to_page' )
        self._controller.sub( self, 'RenamePage', 'rename_page' )
        self._controller.sub( self, 'SetDBLockedStatus', 'db_locked_status' )
        self._controller.sub( self, 'SetMediaFocus', 'set_media_focus' )
        self._controller.sub( self, 'SetTitle', 'main_gui_title' )
        self._controller.sub( self, 'SyncToTagArchive', 'sync_to_tag_archive' )
        
        self._menus = {}
        
        vbox = wx.BoxSizer( wx.VERTICAL )
        
        vbox.Add( self._notebook, CC.FLAGS_EXPAND_SIZER_BOTH_WAYS )
        
        self.SetSizer( vbox )
        
        ClientGUITopLevelWindows.SetInitialTLWSizeAndPosition( self, self._frame_key )
        
        self.Show( True )
        
        self._InitialiseMenubar()
        
        self._RefreshStatusBar()
        
        wx.CallAfter( self._InitialiseSession ) # do this in callafter as some pages want to talk to controller.gui, which doesn't exist yet!
        
        self._bandwidth_timer = wx.Timer( self, id = ID_TIMER_GUI_BANDWIDTH )
        
        self._bandwidth_timer.Start( 1000, wx.TIMER_CONTINUOUS )
        
        self._page_update_timer = wx.Timer( self, id = ID_TIMER_PAGE_UPDATE )
        
        self._page_update_timer.Start( 250, wx.TIMER_CONTINUOUS )
        
        self._ui_update_timer = wx.Timer( self, id = ID_TIMER_UI_UPDATE )
        
        self._ui_update_windows = set()
        
        self._animation_update_timer = wx.Timer( self, id = ID_TIMER_ANIMATION_UPDATE )
        
        self._animation_update_windows = set()
        
        wx.CallAfter( self.Layout ) # some i3 thing--doesn't layout main gui on init for some reason
        
    
    def _AboutWindow( self ):
        
        aboutinfo = wx.adv.AboutDialogInfo()
        
        aboutinfo.SetIcon( self._controller.frame_icon )
        aboutinfo.SetName( 'hydrus client' )
        aboutinfo.SetVersion( str( HC.SOFTWARE_VERSION ) + ', using network version ' + str( HC.NETWORK_VERSION ) )
        
        library_versions = []
        
        library_versions.append( ( 'FFMPEG', HydrusVideoHandling.GetFFMPEGVersion() ) )
        library_versions.append( ( 'OpenCV', cv2.__version__ ) )
        library_versions.append( ( 'openssl', ssl.OPENSSL_VERSION ) )
        library_versions.append( ( 'PIL', PIL.VERSION ) )
        
        if hasattr( PIL, 'PILLOW_VERSION' ):
            
            library_versions.append( ( 'Pillow', PIL.PILLOW_VERSION ) )
            
        
        # 2.7.12 (v2.7.12:d33e0cf91556, Jun 27 2016, 15:24:40) [MSC v.1500 64 bit (AMD64)]
        v = sys.version
        
        if ' ' in v:
            
            v = v.split( ' ' )[0]
            
        
        library_versions.append( ( 'python', v ) )
        
        library_versions.append( ( 'sqlite', sqlite3.sqlite_version ) )
        library_versions.append( ( 'wx', wx.version() ) )
        library_versions.append( ( 'temp dir', HydrusPaths.tempfile.gettempdir() ) )
        
        import locale
        
        l_string = locale.getlocale()[0]
        wxl_string = self._controller._app.locale.GetCanonicalName()
        
        library_versions.append( ( 'locale strings', HydrusData.ToUnicode( ( l_string, wxl_string ) ) ) )
        
        description = 'This client is the media management application of the hydrus software suite.'
        
        description += os.linesep * 2 + os.linesep.join( ( lib + ': ' + version for ( lib, version ) in library_versions ) )
        
        aboutinfo.SetDescription( description )
        
        with open( HC.LICENSE_PATH, 'rb' ) as f: license = f.read()
        
        aboutinfo.SetLicense( license )
        
        aboutinfo.SetDevelopers( [ 'Anonymous' ] )
        aboutinfo.SetWebSite( 'https://hydrusnetwork.github.io/hydrus/' )
        
        wx.adv.AboutBox( aboutinfo )
        
    
    def _AccountInfo( self, service_key ):
        
        with ClientGUIDialogs.DialogTextEntry( self, 'Enter the account\'s account key.' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_OK:
                
                subject_account_key = dlg.GetValue().decode( 'hex' )
                
                service = self._controller.services_manager.GetService( service_key )
                
                response = service.Request( HC.GET, 'account_info', { 'subject_account_key' : subject_account_key } )
                
                account_info = response[ 'account_info' ]
                
                wx.MessageBox( HydrusData.ToUnicode( account_info ) )
                
            
        
    
    def _AnalyzeDatabase( self ):
        
        message = 'This will gather statistical information on the database\'s indices, helping the query planner perform efficiently. It typically happens automatically every few days, but you can force it here. If you have a large database, it will take a few minutes, during which your gui may hang. A popup message will show its status.'
        message += os.linesep * 2
        message += 'A \'soft\' analyze will only reanalyze those indices that are due for a check in the normal db maintenance cycle. If nothing is due, it will return immediately.'
        message += os.linesep * 2
        message += 'A \'full\' analyze will force a run over every index in the database. This can take substantially longer. If you do not have a specific reason to select this, it is probably pointless.'
        
        with ClientGUIDialogs.DialogYesNo( self, message, title = 'Choose how thorough your analyze will be.', yes_label = 'soft', no_label = 'full' ) as dlg:
            
            result = dlg.ShowModal()
            
            if result == wx.ID_YES:
                
                stop_time = HydrusData.GetNow() + 120
                
                self._controller.Write( 'analyze', stop_time = stop_time )
                
            elif result == wx.ID_NO:
                
                self._controller.Write( 'analyze', force_reanalyze = True )
                
            
        
    
    def _AutoRepoSetup( self ):
        
        def do_it():
            
            edit_log = []
            
            service_key = HydrusData.GenerateKey()
            service_type = HC.TAG_REPOSITORY
            name = 'public tag repository'
            
            tag_repo = ClientServices.GenerateService( service_key, service_type, name )
            
            host = 'hydrus.no-ip.org'
            port = 45871
            access_key = '4a285629721ca442541ef2c15ea17d1f7f7578b0c3f4f5f2a05f8f0ab297786f'.decode( 'hex' )
            
            credentials = HydrusNetwork.Credentials( host, port, access_key )
            
            tag_repo.SetCredentials( credentials )
            
            service_key = HydrusData.GenerateKey()
            service_type = HC.FILE_REPOSITORY
            name = 'read-only art file repository'
            
            file_repo = ClientServices.GenerateService( service_key, service_type, name )
            
            host = 'hydrus.no-ip.org'
            port = 45872
            access_key = '8f8a3685abc19e78a92ba61d84a0482b1cfac176fd853f46d93fe437a95e40a5'.decode( 'hex' )
            
            credentials = HydrusNetwork.Credentials( host, port, access_key )
            
            file_repo.SetCredentials( credentials )
            
            all_services = list( self._controller.services_manager.GetServices() )
            
            all_services.append( tag_repo )
            all_services.append( file_repo )
            
            self._controller.SetServices( all_services )
            
            message = 'Auto repo setup done! Check services->review services to see your new services.'
            message += os.linesep * 2
            message += 'The PTR has a lot of tags and will sync a little bit at a time when you are not using the client. Expect it to take a few weeks to sync fully.'
            
            HydrusData.ShowText( message )
            
        
        text = 'This will attempt to set up your client with my repositories\' credentials, letting you tag on the public tag repository and see some files.'
        
        with ClientGUIDialogs.DialogYesNo( self, text ) as dlg:
            
            if dlg.ShowModal() == wx.ID_YES:
                
                self._controller.CallToThread( do_it )
                
            
        
    
    def _AutoServerSetup( self ):
        
        def do_it():
            
            host = '127.0.0.1'
            port = HC.DEFAULT_SERVER_ADMIN_PORT
            
            try:
                
                connection = HydrusNetworking.GetLocalConnection( port )
                connection.close()
                
                already_running = True
                
            except:
                
                already_running = False
                
            
            if already_running:
                
                HydrusData.ShowText( 'The server appears to be already running. Either that, or something else is using port ' + str( HC.DEFAULT_SERVER_ADMIN_PORT ) + '.' )
                
                return
                
            else:
                
                try:
                    
                    HydrusData.ShowText( u'Starting server\u2026' )
                    
                    db_param = '-d="' + self._controller.GetDBDir() + '"'
                    
                    if HC.PLATFORM_WINDOWS:
                        
                        server_frozen_path = os.path.join( HC.BASE_DIR, 'server.exe' )
                        
                    else:
                        
                        server_frozen_path = os.path.join( HC.BASE_DIR, 'server' )
                        
                    
                    if os.path.exists( server_frozen_path ):
                        
                        cmd = '"' + server_frozen_path + '" ' + db_param
                        
                    else:
                        
                        python_executable = sys.executable
                        
                        if python_executable.endswith( 'client.exe' ) or python_executable.endswith( 'client' ):
                            
                            raise Exception( 'Could not automatically set up the server--could not find server executable or python executable.' )
                            
                        
                        if 'pythonw' in python_executable:
                            
                            python_executable = python_executable.replace( 'pythonw', 'python' )
                            
                        
                        server_script_path = os.path.join( HC.BASE_DIR, 'server.py' )
                        
                        cmd = '"' + python_executable + '" "' + server_script_path + '" ' + db_param
                        
                    
                    subprocess.Popen( shlex.split( cmd ) )
                    
                    time_waited = 0
                    
                    while True:
                        
                        time.sleep( 3 )
                        
                        time_waited += 3
                        
                        try:
                            
                            connection = HydrusNetworking.GetLocalConnection( port )
                            
                            connection.close()
                            
                            break
                            
                        except:
                            
                            if time_waited > 30:
                                
                                raise
                                
                            
                        
                    
                except:
                    
                    HydrusData.ShowText( 'I tried to start the server, but something failed!' + os.linesep + traceback.format_exc() )
                    
                    return
                    
                
            
            time.sleep( 5 )
            
            HydrusData.ShowText( u'Creating admin service\u2026' )
            
            admin_service_key = HydrusData.GenerateKey()
            service_type = HC.SERVER_ADMIN
            name = 'local server admin'
            
            admin_service = ClientServices.GenerateService( admin_service_key, service_type, name )
            
            all_services = list( self._controller.services_manager.GetServices() )
            
            all_services.append( admin_service )
            
            self._controller.SetServices( all_services )
            
            admin_service = self._controller.services_manager.GetService( admin_service_key ) # let's refresh it
            
            credentials = HydrusNetwork.Credentials( host, port )
            
            admin_service.SetCredentials( credentials )
            
            response = admin_service.Request( HC.GET, 'access_key', { 'registration_key' : 'init' } )
            
            access_key = response[ 'access_key' ]
            
            credentials = HydrusNetwork.Credentials( host, port, access_key )
            
            admin_service.SetCredentials( credentials )
            
            #
            
            HydrusData.ShowText( 'Admin service initialised.' )
            
            wx.CallAfter( ClientGUIFrames.ShowKeys, 'access', ( access_key, ) )
            
            #
            
            time.sleep( 5 )
            
            HydrusData.ShowText( u'Creating tag and file services\u2026' )
            
            response = admin_service.Request( HC.GET, 'services' )
            
            serverside_services = response[ 'services' ]
            
            service_key = HydrusData.GenerateKey()
            
            tag_service = HydrusNetwork.GenerateService( service_key, HC.TAG_REPOSITORY, 'tag service', HC.DEFAULT_SERVICE_PORT )
            
            serverside_services.append( tag_service )
            
            service_key = HydrusData.GenerateKey()
            
            file_service = HydrusNetwork.GenerateService( service_key, HC.FILE_REPOSITORY, 'file service', HC.DEFAULT_SERVICE_PORT + 1 )
            
            serverside_services.append( file_service )
            
            response = admin_service.Request( HC.POST, 'services', { 'services' : serverside_services } )
            
            service_keys_to_access_keys = response[ 'service_keys_to_access_keys' ]
            
            deletee_service_keys = []
            
            with HG.dirty_object_lock:
                
                self._controller.WriteSynchronous( 'update_server_services', admin_service_key, serverside_services, service_keys_to_access_keys, deletee_service_keys )
                
                self._controller.RefreshServices()
                
            
            HydrusData.ShowText( 'Done! Check services->review services to see your new server and its services.' )
            
        
        text = 'This will attempt to start the server in the same install directory as this client, initialise it, and store the resultant admin accounts in the client.'
        
        with ClientGUIDialogs.DialogYesNo( self, text ) as dlg:
            
            if dlg.ShowModal() == wx.ID_YES:
                
                self._controller.CallToThread( do_it )
                
            
        
    
    def _BackupDatabase( self ):
        
        path = self._new_options.GetNoneableString( 'backup_path' )
        
        if path is None:
            
            wx.MessageBox( 'No backup path is set!' )
            
            return
            
        
        if not os.path.exists( path ):
            
            wx.MessageBox( 'The backup path does not exist--creating it now.' )
            
            HydrusPaths.MakeSureDirectoryExists( path )
            
        
        client_db_path = os.path.join( path, 'client.db' )
        
        if os.path.exists( client_db_path ):
            
            action = 'Update the existing'
            
        else:
            
            action = 'Create a new'
            
        
        text = action + ' backup at "' + path + '"?'
        text += os.linesep * 2
        text += 'The database will be locked while the backup occurs, which may lock up your gui as well.'
        
        with ClientGUIDialogs.DialogYesNo( self, text ) as dlg_yn:
            
            if dlg_yn.ShowModal() == wx.ID_YES:
                
                self._notebook.SaveGUISession( 'last session' )
                
                # session save causes a db read in the menu refresh, so let's put this off just a bit
                self._controller.CallLater( 1.5, self._controller.Write, 'backup', path )
                
            
        
    
    def _BackupService( self, service_key ):
        
        def do_it():
            
            started = HydrusData.GetNow()
            
            service = self._controller.services_manager.GetService( service_key )
            
            service.Request( HC.POST, 'backup' )
            
            HydrusData.ShowText( 'Server backup started!' )
            
            time.sleep( 10 )
            
            result = service.Request( HC.GET, 'busy' )
            
            while result == '1':
                
                if self._controller.ViewIsShutdown():
                    
                    return
                    
                
                time.sleep( 10 )
                
                result = service.Request( HC.GET, 'busy' )
                
            
            it_took = HydrusData.GetNow() - started
            
            HydrusData.ShowText( 'Server backup done in ' + HydrusData.ConvertTimeDeltaToPrettyString( it_took ) + '!' )
            
        
        message = 'This will tell the server to lock and copy its database files. It will probably take a few minutes to complete, during which time it will not be able to serve any requests.'
        
        with ClientGUIDialogs.DialogYesNo( self, message, yes_label = 'do it', no_label = 'forget it' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_YES:
                
                self._controller.CallToThread( do_it )
                
            
        
    
    def _CheckDBIntegrity( self ):
        
        message = 'This will check the database for missing and invalid entries. It may take several minutes to complete.'
        
        with ClientGUIDialogs.DialogYesNo( self, message, title = 'Run integrity check?', yes_label = 'do it', no_label = 'forget it' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_YES:
                
                self._controller.Write( 'db_integrity' )
                
            
        
    
    def _CheckFileIntegrity( self ):
        
        client_files_manager = self._controller.client_files_manager
        
        message = 'This will go through all the files the database thinks it has and check that they actually exist. Any files that are missing will be deleted from the internal record.'
        message += os.linesep * 2
        message += 'You can perform a quick existence check, which will only look to see if a file exists, or a thorough content check, which will also make sure existing files are not corrupt or otherwise incorrect.'
        message += os.linesep * 2
        message += 'The thorough check will have to read all of your files\' content, which can take a long time. You should probably only do it if you suspect hard drive corruption and are now working on a safe drive.'
        
        with ClientGUIDialogs.DialogYesNo( self, message, title = 'Choose how thorough your integrity check will be.', yes_label = 'quick', no_label = 'thorough' ) as dlg:
            
            result = dlg.ShowModal()
            
            if result == wx.ID_YES:
                
                self._controller.CallToThread( client_files_manager.CheckFileIntegrity, 'quick' )
                
            elif result == wx.ID_NO:
                
                text = 'If an existing file is found to be corrupt/incorrect, would you like to move it or delete it?'
                
                with ClientGUIDialogs.DialogYesNo( self, text, title = 'Choose what do to with bad files.', yes_label = 'move', no_label = 'delete' ) as dlg_2:
                    
                    result = dlg_2.ShowModal()
                    
                    if result == wx.ID_YES:
                        
                        with wx.DirDialog( self, 'Select location.' ) as dlg_3:
                            
                            if dlg_3.ShowModal() == wx.ID_OK:
                                
                                path = HydrusData.ToUnicode( dlg_3.GetPath() )
                                
                                self._controller.CallToThread( client_files_manager.CheckFileIntegrity, 'thorough', path )
                                
                            
                        
                    elif result == wx.ID_NO:
                        
                        self._controller.CallToThread( client_files_manager.CheckFileIntegrity, 'thorough' )
                        
                    
                
            
        
    
    def _CheckImportFolder( self, name = None ):
        
        if self._controller.options[ 'pause_import_folders_sync' ]:
            
            HydrusData.ShowText( 'Import folders are currently paused under the \'services\' menu. Please unpause them and try this again.' )
            
        
        if name is None:
            
            import_folders = self._controller.Read( 'serialisable_named', HydrusSerialisable.SERIALISABLE_TYPE_IMPORT_FOLDER )
            
        else:
            
            import_folder = self._controller.Read( 'serialisable_named', HydrusSerialisable.SERIALISABLE_TYPE_IMPORT_FOLDER, name )
            
            import_folders = [ import_folder ]
            
        
        for import_folder in import_folders:
            
            import_folder.CheckNow()
            
            self._controller.WriteSynchronous( 'serialisable', import_folder )
            
        
        self._controller.pub( 'notify_new_import_folders' )
        
    
    def _ClearOrphans( self ):
        
        text = 'This will iterate through every file in your database\'s file storage, removing any it does not expect to be there. It may take some time.'
        text += os.linesep * 2
        text += 'Files and thumbnails will be inaccessible while this occurs, so it is best to leave the client alone until it is done.'
        
        with ClientGUIDialogs.DialogYesNo( self, text, yes_label = 'do it', no_label = 'forget it' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_YES:
                
                text = 'What would you like to do with the orphaned files? Note that all orphaned thumbnails will be deleted.'
                
                client_files_manager = self._controller.client_files_manager
                
                with ClientGUIDialogs.DialogYesNo( self, text, title = 'Choose what do to with the orphans.', yes_label = 'move them somewhere', no_label = 'delete them' ) as dlg_2:
                    
                    result = dlg_2.ShowModal()
                    
                    if result == wx.ID_YES:
                        
                        with wx.DirDialog( self, 'Select location.' ) as dlg_3:
                            
                            if dlg_3.ShowModal() == wx.ID_OK:
                                
                                path = HydrusData.ToUnicode( dlg_3.GetPath() )
                                
                                self._controller.CallToThread( client_files_manager.ClearOrphans, path )
                                
                            
                        
                    elif result == wx.ID_NO:
                        
                        self._controller.CallToThread( client_files_manager.ClearOrphans )
                        
                    
                
            
        
    
    def _DebugMakeSomePopups( self ):
        
        for i in range( 1, 7 ):
            
            HydrusData.ShowText( 'This is a test popup message -- ' + str( i ) )
            
        
        #
        
        job_key = ClientThreading.JobKey()
        
        job_key.SetVariable( 'popup_title', u'\u24c9\u24d7\u24d8\u24e2 \u24d8\u24e2 \u24d0 \u24e3\u24d4\u24e2\u24e3 \u24e4\u24dd\u24d8\u24d2\u24de\u24d3\u24d4 \u24dc\u24d4\u24e2\u24e2\u24d0\u24d6\u24d4' )
        
        job_key.SetVariable( 'popup_text_1', u'\u24b2\u24a0\u24b2 \u24a7\u249c\u249f' )
        job_key.SetVariable( 'popup_text_2', u'p\u0250\u05df \u028d\u01dd\u028d' )
        
        self._controller.pub( 'message', job_key )
        
        #
        
        job_key = ClientThreading.JobKey( pausable = True, cancellable = True )
        
        job_key.SetVariable( 'popup_title', 'test job' )
        
        job_key.SetVariable( 'popup_text_1', 'Currently processing test job 5/8' )
        job_key.SetVariable( 'popup_gauge_1', ( 5, 8 ) )
        
        self._controller.pub( 'message', job_key )
        
        self._controller.CallLater( 2.0, job_key.SetVariable, 'popup_text_2', 'Pulsing subjob' )
        
        self._controller.CallLater( 2.0, job_key.SetVariable, 'popup_gauge_2', ( 0, None ) )
        
        #
        
        e = HydrusExceptions.DataMissing( 'This is a test exception' )
        
        HydrusData.ShowException( e )
        
        #
        
        for i in range( 1, 4 ):
            
            self._controller.CallLater( 0.5 * i, HydrusData.ShowText, 'This is a delayed popup message -- ' + str( i ) )
            
        
    
    def _DebugPrintGarbage( self ):
        
        HydrusData.ShowText( 'Printing garbage to log' )
        
        gc.collect()
        
        count = collections.Counter()
        
        class_count = collections.Counter()
        
        for o in gc.get_objects():
            
            count[ type( o ) ] += 1
            
            if isinstance( o, types.InstanceType ): class_count[ o.__class__.__name__ ] += 1
            elif isinstance( o, types.BuiltinFunctionType ): class_count[ o.__name__ ] += 1
            elif isinstance( o, types.BuiltinMethodType ): class_count[ o.__name__ ] += 1
            
        
        HydrusData.Print( 'gc types:' )
        
        for ( k, v ) in count.items():
            
            if v > 100:
                
                HydrusData.Print( ( k, v ) )
                
            
        
        HydrusData.Print( 'gc classes:' )
        
        for ( k, v ) in class_count.items():
            
            if v > 100:
                
                HydrusData.Print( ( k, v ) )
                
            
        
        HydrusData.Print( 'uncollectable garbage: ' + HydrusData.ToUnicode( gc.garbage ) )
        
        HydrusData.DebugPrint( 'garbage printing finished' )
        
    
    def _DeleteGUISession( self, name ):
        
        message = 'Delete session "' + name + '"?'
        
        with ClientGUIDialogs.DialogYesNo( self, message, title = 'Delete session?' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_YES:
                
                self._controller.Write( 'delete_serialisable_named', HydrusSerialisable.SERIALISABLE_TYPE_GUI_SESSION, name )
                
                self._controller.pub( 'notify_new_sessions' )
                
            
        
    
    def _DeletePending( self, service_key ):
        
        service = self._controller.services_manager.GetService( service_key )
        
        with ClientGUIDialogs.DialogYesNo( self, 'Are you sure you want to delete the pending data for ' + service.GetName() + '?' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_YES: self._controller.Write( 'delete_pending', service_key )
            
        
    
    def _DeleteServiceInfo( self ):
        
        with ClientGUIDialogs.DialogYesNo( self, 'Are you sure you want to clear the cached service info? Rebuilding it may slow some GUI elements for a little while.' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_YES: self._controller.Write( 'delete_service_info' )
            
        
    
    def _DestroyPages( self, pages ):
        
        with self._lock:
            
            for page in pages:
                
                self._deleted_page_keys.add( page.GetPageKey() )
                
            
        
        for page in pages:
            
            page.CleanBeforeDestroy()
            
            page.Destroy()
            
        
    
    def _DestroyTimers( self ):
        
        if self._bandwidth_timer is not None:
            
            self._bandwidth_timer.Stop()
            
            self._bandwidth_timer = None
            
        
        if self._page_update_timer is not None:
            
            self._page_update_timer.Stop()
            
            self._page_update_timer = None
            
        
        if self._ui_update_timer is not None:
            
            self._ui_update_timer.Stop()
            
            self._ui_update_timer = None
            
        
        if self._animation_update_timer is not None:
            
            self._animation_update_timer.Stop()
            
            self._animation_update_timer = None
            
        
    
    def _DirtyMenu( self, name ):
        
        if name not in self._dirty_menus:
            
            ( menu, label, show ) = self._menus[ name ]
            
            if show:
                
                menu_index = self._menubar.FindMenu( label )
                
                self._menubar.EnableTop( menu_index, False )
                
            
            self._dirty_menus.add( name )
            
        
    
    def _FetchIP( self, service_key ):
        
        with ClientGUIDialogs.DialogTextEntry( self, 'Enter the file\'s hash.' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_OK:
                
                hash = dlg.GetValue().decode( 'hex' )
                
                service = self._controller.services_manager.GetService( service_key )
                
                with wx.BusyCursor(): response = service.Request( HC.GET, 'ip', { 'hash' : hash } )
                
                ip = response[ 'ip' ]
                timestamp = response[ 'timestamp' ]
                
                gmt_time = HydrusData.ConvertTimestampToPrettyTime( timestamp, in_gmt = True )
                local_time = HydrusData.ConvertTimestampToPrettyTime( timestamp )
                
                text = 'File Hash: ' + hash.encode( 'hex' )
                text += os.linesep
                text += 'Uploader\'s IP: ' + ip
                text += 'Upload Time (GMT): ' + gmt_time
                text += 'Upload Time (Your time): ' + local_time
                
                HydrusData.Print( text )
                
                wx.MessageBox( text + os.linesep * 2 + 'This has been written to the log.' )
                
            
        
    
    def _GenerateMenuInfo( self, name ):
        
        menu = wx.Menu()
        
        def file():
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'import files', 'Add new files to the database.', self._ImportFiles )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            import_folder_names = self._controller.Read( 'serialisable_names', HydrusSerialisable.SERIALISABLE_TYPE_IMPORT_FOLDER )
            
            if len( import_folder_names ) > 0:
                
                submenu = wx.Menu()
                
                if len( import_folder_names ) > 1:
                    
                    ClientGUIMenus.AppendMenuItem( self, submenu, 'check all', 'Check all import folders.', self._CheckImportFolder )
                    
                    ClientGUIMenus.AppendSeparator( submenu )
                    
                
                for name in import_folder_names:
                    
                    ClientGUIMenus.AppendMenuItem( self, submenu, name, 'Check this import folder now.', self._CheckImportFolder, name )
                    
                
                ClientGUIMenus.AppendMenu( menu, submenu, 'check import folder now' )
                
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage import folders', 'Manage folders from which the client can automatically import.', self._ManageImportFolders )
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage export folders', 'Manage folders to which the client can automatically export.', self._ManageExportFolders )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            open = wx.Menu()
            
            ClientGUIMenus.AppendMenuItem( self, open, 'installation directory', 'Open the installation directory for this client.', self._OpenInstallFolder )
            ClientGUIMenus.AppendMenuItem( self, open, 'database directory', 'Open the database directory for this instance of the client.', self._OpenDBFolder )
            ClientGUIMenus.AppendMenuItem( self, open, 'quick export directory', 'Open the export directory so you can easily access the files you have exported.', self._OpenExportFolder )
            
            ClientGUIMenus.AppendMenu( menu, open, 'open' )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'options', 'Change how the client operates.', self._ManageOptions )
            ClientGUIMenus.AppendMenuItem( self, menu, 'shortcuts', 'Edit the shortcuts your client responds to.', self._ManageShortcuts )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            we_borked_linux_pyinstaller = HC.PLATFORM_LINUX and not HC.RUNNING_FROM_SOURCE
            
            if not we_borked_linux_pyinstaller:
                
                ClientGUIMenus.AppendMenuItem( self, menu, 'restart', 'Shut the client down and then start it up again.', self.Exit, restart = True )
                
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'exit', 'Shut the client down.', self.Exit )
            
            return ( menu, '&file', True )
            
        
        def undo():
            
            with self._lock:
                
                have_closed_pages = len( self._closed_pages ) > 0
                
            
            undo_manager = self._controller.GetManager( 'undo' )
            
            ( undo_string, redo_string ) = undo_manager.GetUndoRedoStrings()
            
            have_undo_stuff = undo_string is not None or redo_string is not None
            
            if have_closed_pages or have_undo_stuff:
                
                show = True
                
                if undo_string is not None:
                    
                    ClientGUIMenus.AppendMenuItem( self, menu, undo_string, 'Undo last operation.', self._controller.pub, 'undo' )
                    
                
                if redo_string is not None:
                    
                    ClientGUIMenus.AppendMenuItem( self, menu, redo_string, 'Redo last operation.', self._controller.pub, 'redo' )
                    
                
                if have_closed_pages:
                    
                    ClientGUIMenus.AppendSeparator( menu )
                    
                    undo_pages = wx.Menu()
                    
                    ClientGUIMenus.AppendMenuItem( self, undo_pages, 'clear all', 'Remove all closed pages from memory.', self.DeleteAllClosedPages )
                    
                    undo_pages.AppendSeparator()
                    
                    args = []
                    
                    with self._lock:
                        
                        for ( i, ( time_closed, page ) ) in enumerate( self._closed_pages ):
                            
                            name = page.GetDisplayName()
                            
                            args.append( ( i, name + ' - ' + page.GetPrettyStatus() ) )
                            
                        
                    
                    args.reverse() # so that recently closed are at the top
                    
                    for ( index, name ) in args:
                        
                        ClientGUIMenus.AppendMenuItem( self, undo_pages, name, 'Restore this page.', self._UnclosePage, index )
                        
                    
                    ClientGUIMenus.AppendMenu( menu, undo_pages, 'closed pages' )
                    
                
            else:
                
                show = False
                
            
            return ( menu, '&undo', show )
            
        
        def pages():
            
            if self._controller.new_options.GetBoolean( 'advanced_mode' ):
                
                ( total_active_page_count, total_closed_page_count ) = self.GetTotalPageCounts()
                
                ClientGUIMenus.AppendMenuLabel( menu, HydrusData.ConvertIntToPrettyString( total_active_page_count ) + ' pages open', 'You have this many pages open.' )
                
                ClientGUIMenus.AppendSeparator( menu )
                
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'refresh', 'If the current page has a search, refresh it.', self._Refresh )
            ClientGUIMenus.AppendMenuItem( self, menu, 'show/hide management and preview panels', 'Show or hide the panels on the left.', self._ShowHideSplitters )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            gui_session_names = self._controller.Read( 'serialisable_names', HydrusSerialisable.SERIALISABLE_TYPE_GUI_SESSION )
            
            sessions = wx.Menu()
            
            if len( gui_session_names ) > 0:
                
                load = wx.Menu()
                
                for name in gui_session_names:
                    
                    ClientGUIMenus.AppendMenuItem( self, load, name, 'Close all other pages and load this session.', self._notebook.LoadGUISession, name )
                    
                
                ClientGUIMenus.AppendMenu( sessions, load, 'clear and load' )
                
                append = wx.Menu()
                
                for name in gui_session_names:
                    
                    ClientGUIMenus.AppendMenuItem( self, append, name, 'Append this session to whatever pages are already open.', self._notebook.AppendGUISession, name )
                    
                
                ClientGUIMenus.AppendMenu( sessions, append, 'append' )
                
            
            save = wx.Menu()
            
            for name in gui_session_names:
                
                if name == 'last session':
                    
                    continue
                    
                
                ClientGUIMenus.AppendMenuItem( self, save, name, 'Save the existing open pages as a session.', self._notebook.SaveGUISession, name )
                
            
            ClientGUIMenus.AppendMenuItem( self, save, 'as new session', 'Save the existing open pages as a session.', self._notebook.SaveGUISession )
            
            ClientGUIMenus.AppendMenu( sessions, save, 'save' )
            
            if len( gui_session_names ) > 0 and gui_session_names != [ 'last session' ]:
                
                delete = wx.Menu()
                
                for name in gui_session_names:
                    
                    if name != 'last session':
                        
                        ClientGUIMenus.AppendMenuItem( self, delete, name, 'Delete this session.', self._DeleteGUISession, name )
                        
                    
                
                ClientGUIMenus.AppendMenu( sessions, delete, 'delete' )
                
            
            ClientGUIMenus.AppendMenu( menu, sessions, 'sessions' )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'pick a new page', 'Choose a new page to open.', self._notebook.ChooseNewPageForDeepestNotebook )
            
            #
            
            search_menu = wx.Menu()
            
            services = self._controller.services_manager.GetServices()
            
            petition_permissions = [ ( content_type, HC.PERMISSION_ACTION_OVERRULE ) for content_type in HC.REPOSITORY_CONTENT_TYPES ]
            
            repositories = [ service for service in services if service.GetServiceType() in HC.REPOSITORIES ]
            
            file_repositories = [ service for service in repositories if service.GetServiceType() == HC.FILE_REPOSITORY ]
            
            petition_resolvable_repositories = [ repository for repository in repositories if True in ( repository.HasPermission( content_type, action ) for ( content_type, action ) in petition_permissions ) ]
            
            ClientGUIMenus.AppendMenuItem( self, search_menu, 'my files', 'Open a new search tab for your files.', self._notebook.NewPageQuery, CC.LOCAL_FILE_SERVICE_KEY, on_deepest_notebook = True )
            ClientGUIMenus.AppendMenuItem( self, search_menu, 'trash', 'Open a new search tab for your recently deleted files.', self._notebook.NewPageQuery, CC.TRASH_SERVICE_KEY, on_deepest_notebook = True )
            
            for service in file_repositories:
                
                ClientGUIMenus.AppendMenuItem( self, search_menu, service.GetName(), 'Open a new search tab for ' + service.GetName() + '.', self._notebook.NewPageQuery, service.GetServiceKey(), on_deepest_notebook = True )
                
            
            ClientGUIMenus.AppendMenu( menu, search_menu, 'new search page' )
            
            #
            
            if len( petition_resolvable_repositories ) > 0:
                
                petition_menu = wx.Menu()
                
                for service in petition_resolvable_repositories:
                    
                    ClientGUIMenus.AppendMenuItem( self, petition_menu, service.GetName(), 'Open a new petition page for ' + service.GetName() + '.', self._notebook.NewPagePetitions, service.GetServiceKey(), on_deepest_notebook = True )
                    
                
                ClientGUIMenus.AppendMenu( menu, petition_menu, 'new petition page' )
                
            
            #
            
            download_menu = wx.Menu()
            
            ClientGUIMenus.AppendMenuItem( self, download_menu, 'url download', 'Open a new tab to download some raw urls.', self._notebook.NewPageImportURLs, on_deepest_notebook = True )
            ClientGUIMenus.AppendMenuItem( self, download_menu, 'thread watcher', 'Open a new tab to watch a thread.', self._notebook.NewPageImportThreadWatcher, on_deepest_notebook = True )
            ClientGUIMenus.AppendMenuItem( self, download_menu, 'webpage of images', 'Open a new tab to download files from generic galleries or threads.', self._notebook.NewPageImportPageOfImages, on_deepest_notebook = True )
            
            gallery_menu = wx.Menu()
            
            ClientGUIMenus.AppendMenuItem( self, gallery_menu, 'booru', 'Open a new tab to download files from a booru.', self._notebook.NewPageImportBooru, on_deepest_notebook = True )
            ClientGUIMenus.AppendMenuItem( self, gallery_menu, 'deviant art', 'Open a new tab to download files from Deviant Art.', self._notebook.NewPageImportGallery, ClientDownloading.GalleryIdentifier( HC.SITE_TYPE_DEVIANT_ART ), on_deepest_notebook = True )
            
            hf_submenu = wx.Menu()
            
            ClientGUIMenus.AppendMenuItem( self, hf_submenu, 'by artist', 'Open a new tab to download files from Hentai Foundry.', self._notebook.NewPageImportGallery, ClientDownloading.GalleryIdentifier( HC.SITE_TYPE_HENTAI_FOUNDRY_ARTIST ), on_deepest_notebook = True )
            ClientGUIMenus.AppendMenuItem( self, hf_submenu, 'by tags', 'Open a new tab to download files from Hentai Foundry.', self._notebook.NewPageImportGallery, ClientDownloading.GalleryIdentifier( HC.SITE_TYPE_HENTAI_FOUNDRY_TAGS ), on_deepest_notebook = True )
            
            ClientGUIMenus.AppendMenu( gallery_menu, hf_submenu, 'hentai foundry' )
            
            ClientGUIMenus.AppendMenuItem( self, gallery_menu, 'newgrounds', 'Open a new tab to download files from Newgrounds.', self._notebook.NewPageImportGallery, ClientDownloading.GalleryIdentifier( HC.SITE_TYPE_NEWGROUNDS ), on_deepest_notebook = True )
            
            result = self._controller.Read( 'serialisable_simple', 'pixiv_account' )
            
            if result is not None:
                
                pixiv_submenu = wx.Menu()
                
                ClientGUIMenus.AppendMenuItem( self, pixiv_submenu, 'by artist id', 'Open a new tab to download files from Pixiv.', self._notebook.NewPageImportGallery, ClientDownloading.GalleryIdentifier( HC.SITE_TYPE_PIXIV_ARTIST_ID ), on_deepest_notebook = True )
                #ClientGUIMenus.AppendMenuItem( self, pixiv_submenu, 'by tag', 'Open a new tab to download files from Pixiv.', self._notebook.NewPageImportGallery, ClientDownloading.GalleryIdentifier( HC.SITE_TYPE_PIXIV_TAG ), on_deepest_notebook = True )
                
                ClientGUIMenus.AppendMenu( gallery_menu, pixiv_submenu, 'pixiv' )
                
            
            ClientGUIMenus.AppendMenuItem( self, gallery_menu, 'tumblr', 'Open a new tab to download files from tumblr.', self._notebook.NewPageImportGallery, ClientDownloading.GalleryIdentifier( HC.SITE_TYPE_TUMBLR ), on_deepest_notebook = True )
            
            ClientGUIMenus.AppendMenu( download_menu, gallery_menu, 'gallery' )
            ClientGUIMenus.AppendMenu( menu, download_menu, 'new download page' )
            
            #
            
            download_popup_menu = wx.Menu()
            
            ClientGUIMenus.AppendMenuItem( self, download_popup_menu, 'a youtube video', 'Enter a YouTube URL and choose which formats you would like to download', self._StartYoutubeDownload )
            
            has_ipfs = len( [ service for service in services if service.GetServiceType() == HC.IPFS ] )
            
            if has_ipfs:
                
                ClientGUIMenus.AppendMenuItem( self, download_popup_menu, 'an ipfs multihash', 'Enter an IPFS multihash and attempt to import whatever is returned.', self._StartIPFSDownload )
                
            
            ClientGUIMenus.AppendMenu( menu, download_popup_menu, 'new download popup' )
            
            #
            
            special_menu = wx.Menu()
            
            ClientGUIMenus.AppendMenuItem( self, special_menu, 'page of pages', 'Open a new tab that can hold more tabs.', self._notebook.NewPagesNotebook, on_deepest_notebook = True )
            ClientGUIMenus.AppendMenuItem( self, special_menu, 'duplicates processing', 'Open a new tab to discover and filter duplicate files.', self._notebook.NewPageDuplicateFilter, on_deepest_notebook = True )
            
            ClientGUIMenus.AppendMenu( menu, special_menu, 'new special page' )
            
            #
            
            return ( menu, '&pages', True )
            
        
        def database():
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'set a password', 'Set a simple password for the database so only you can open it in the client.', self._SetPassword )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            backup_path = self._new_options.GetNoneableString( 'backup_path' )
            
            if backup_path is None:
                
                ClientGUIMenus.AppendMenuItem( self, menu, 'set up a database backup location', 'Choose a path to back the database up to.', self._SetupBackupPath )
                
            else:
                
                ClientGUIMenus.AppendMenuItem( self, menu, 'update database backup', 'Back the database up to an external location.', self._BackupDatabase )
                ClientGUIMenus.AppendMenuItem( self, menu, 'change database backup location', 'Choose a path to back the database up to.', self._SetupBackupPath )
                
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'restore from a database backup', 'Restore the database from an external location.', self._controller.RestoreDatabase )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'migrate database', 'Review and manage the locations your database is stored.', self._MigrateDatabase )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            submenu = wx.Menu()
            
            ClientGUIMenus.AppendMenuItem( self, submenu, 'vacuum', 'Defrag the database by completely rebuilding it.', self._VacuumDatabase )
            ClientGUIMenus.AppendMenuItem( self, submenu, 'analyze', 'Optimise slow queries by running statistical analyses on the database.', self._AnalyzeDatabase )
            ClientGUIMenus.AppendMenuItem( self, submenu, 'clear orphans', 'Clear out surplus files that have found their way into the file structure.', self._ClearOrphans )
            
            ClientGUIMenus.AppendMenu( menu, submenu, 'maintain' )
            
            submenu = wx.Menu()
            
            ClientGUIMenus.AppendMenuItem( self, submenu, 'database integrity', 'Have the database examine all its records for internal consistency.', self._CheckDBIntegrity )
            ClientGUIMenus.AppendMenuItem( self, submenu, 'file integrity', 'Have the database check if it truly has the files it thinks it does, and remove records when not.', self._CheckFileIntegrity )
            
            ClientGUIMenus.AppendMenu( menu, submenu, 'check' )
            
            submenu = wx.Menu()
            
            ClientGUIMenus.AppendMenuItem( self, submenu, 'autocomplete cache', 'Delete and recreate the tag autocomplete cache, fixing any miscounts.', self._RegenerateACCache )
            ClientGUIMenus.AppendMenuItem( self, submenu, 'similar files search metadata', 'Delete and recreate the similar files search phashes.', self._RegenerateSimilarFilesPhashes )
            ClientGUIMenus.AppendMenuItem( self, submenu, 'similar files search tree', 'Delete and recreate the similar files search tree.', self._RegenerateSimilarFilesTree )
            ClientGUIMenus.AppendMenuItem( self, submenu, 'all thumbnails', 'Delete all thumbnails and regenerate them from their original files.', self._RegenerateThumbnails )
            
            ClientGUIMenus.AppendMenu( menu, submenu, 'regenerate' )
            
            return ( menu, '&database', True )
            
        
        def pending():
            
            nums_pending = self._controller.Read( 'nums_pending' )
            
            total_num_pending = 0
            
            for ( service_key, info ) in nums_pending.items():
                
                service = self._controller.services_manager.GetService( service_key )
                
                service_type = service.GetServiceType()
                name = service.GetName()
                
                if service_type == HC.TAG_REPOSITORY:
                    
                    pending_phrase = 'tag data to upload'
                    petitioned_phrase = 'tag data to petition'
                    
                elif service_type == HC.FILE_REPOSITORY:
                    
                    pending_phrase = 'files to upload'
                    petitioned_phrase = 'files to petition'
                    
                elif service_type == HC.IPFS:
                    
                    pending_phrase = 'files to pin'
                    petitioned_phrase = 'files to unpin'
                    
                
                if service_type == HC.TAG_REPOSITORY:
                    
                    num_pending = info[ HC.SERVICE_INFO_NUM_PENDING_MAPPINGS ] + info[ HC.SERVICE_INFO_NUM_PENDING_TAG_SIBLINGS ] + info[ HC.SERVICE_INFO_NUM_PENDING_TAG_PARENTS ]
                    num_petitioned = info[ HC.SERVICE_INFO_NUM_PETITIONED_MAPPINGS ] + info[ HC.SERVICE_INFO_NUM_PETITIONED_TAG_SIBLINGS ] + info[ HC.SERVICE_INFO_NUM_PETITIONED_TAG_PARENTS ]
                    
                elif service_type in ( HC.FILE_REPOSITORY, HC.IPFS ):
                    
                    num_pending = info[ HC.SERVICE_INFO_NUM_PENDING_FILES ]
                    num_petitioned = info[ HC.SERVICE_INFO_NUM_PETITIONED_FILES ]
                    
                
                if num_pending + num_petitioned > 0:
                    
                    submenu = wx.Menu()
                    
                    ClientGUIMenus.AppendMenuItem( self, submenu, 'commit', 'Upload ' + name + '\'s pending content.', self._UploadPending, service_key )
                    ClientGUIMenus.AppendMenuItem( self, submenu, 'forget', 'Clear ' + name + '\'s pending content.', self._DeletePending, service_key )
                    
                    submessages = []
                    
                    if num_pending > 0:
                        
                        submessages.append( HydrusData.ConvertIntToPrettyString( num_pending ) + ' ' + pending_phrase )
                        
                    
                    if num_petitioned > 0:
                        
                        submessages.append( HydrusData.ConvertIntToPrettyString( num_petitioned ) + ' ' + petitioned_phrase )
                        
                    
                    message = name + ': ' + ', '.join( submessages )
                    
                    ClientGUIMenus.AppendMenu( menu, submenu, message )
                    
                
                total_num_pending += num_pending + num_petitioned
                
            
            show = total_num_pending > 0
            
            return ( menu, '&pending (' + HydrusData.ConvertIntToPrettyString( total_num_pending ) + ')', show )
            
        
        def network():
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'review bandwidth usage', 'See where you are consuming data.', self._ReviewBandwidth )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage subscriptions', 'Change the queries you want the client to regularly import from.', self._ManageSubscriptions )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            # and transition this to 'manage logins'
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage pixiv account', 'Set up your pixiv username and password.', self._ManagePixivAccount )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage boorus', 'Change the html parsing information for boorus to download from.', self._ManageBoorus )
            # manage downloaders, or maybe just rename the parsing scripts stuff
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage parsing scripts', 'Manage how the client parses different types of web content.', self._ManageParsingScripts )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuLabel( menu, '(This section is under construction)' )
            
            # this will be the easy-mode 'export ability to download from blahbooru' that'll bundle it all into a nice package with a neat png.
            # need a name for this that isn't 'downloader', or maybe it should be, and I should rename downloaders below to 'gallery query generator' or whatever.
            
            ClientGUIMenus.AppendMenuLabel( menu, 'review and import/export download capability', 'Review where you can download from and import or export that data in order to share with other users.' )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuLabel( menu, '(This section is under construction)' )
            
            # maybe put this in a submenu, or hide it all behind advanced mode
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage url classes', 'Configure which URLs the client can recognise.', self._ManageURLMatches )
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage parsers', 'Manage the client\'s parsers, which convert URL content into hydrus metadata.', self._ManageParsers )
            ClientGUIMenus.AppendMenuLabel( menu, 'manage downloaders', 'Manage the client\' downloaders, which convert search terms into URLs.' )
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage url class links', 'Configure how URLs present across the client.', self._ManageURLMatchLinks )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage http headers', 'Configure how the client talks to the network.', self._ManageNetworkHeaders )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage upnp', 'If your router supports it, see and edit your current UPnP NAT traversal mappings.', self._ManageUPnP )
            
            return ( menu, '&network', True )
            
        
        def services():
            
            tag_services = self._controller.services_manager.GetServices( ( HC.TAG_REPOSITORY, ) )
            file_services = self._controller.services_manager.GetServices( ( HC.FILE_REPOSITORY, ) )
            
            submenu = wx.Menu()
            
            ClientGUIMenus.AppendMenuCheckItem( self, submenu, 'export folders synchronisation', 'Pause the client\'s export folders.', HC.options[ 'pause_export_folders_sync' ], self._PauseSync, 'export_folders' )
            ClientGUIMenus.AppendMenuCheckItem( self, submenu, 'import folders synchronisation', 'Pause the client\'s import folders.', HC.options[ 'pause_import_folders_sync' ], self._PauseSync, 'import_folders' )
            ClientGUIMenus.AppendMenuCheckItem( self, submenu, 'repositories synchronisation', 'Pause the client\'s synchronisation with hydrus repositories.', HC.options[ 'pause_repo_sync' ], self._PauseSync, 'repo' )
            ClientGUIMenus.AppendMenuCheckItem( self, submenu, 'subscriptions synchronisation', 'Pause the client\'s synchronisation with website subscriptions.', HC.options[ 'pause_subs_sync' ], self._PauseSync, 'subs' )
            
            ClientGUIMenus.AppendMenu( menu, submenu, 'pause' )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'review services', 'Look at the services your client connects to.', self._ReviewServices )
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage services', 'Edit the services your client connects to.', self._ManageServices )
            
            repository_admin_permissions = [ ( HC.CONTENT_TYPE_ACCOUNTS, HC.PERMISSION_ACTION_CREATE ), ( HC.CONTENT_TYPE_ACCOUNTS, HC.PERMISSION_ACTION_OVERRULE ), ( HC.CONTENT_TYPE_ACCOUNT_TYPES, HC.PERMISSION_ACTION_OVERRULE ) ]
            
            repositories = self._controller.services_manager.GetServices( HC.REPOSITORIES )
            admin_repositories = [ service for service in repositories if True in ( service.HasPermission( content_type, action ) for ( content_type, action ) in repository_admin_permissions ) ]
            
            servers_admin = self._controller.services_manager.GetServices( ( HC.SERVER_ADMIN, ) )
            server_admins = [ service for service in servers_admin if service.HasPermission( HC.CONTENT_TYPE_SERVICES, HC.PERMISSION_ACTION_OVERRULE ) ]
            
            if len( admin_repositories ) > 0 or len( server_admins ) > 0:
                
                admin_menu = wx.Menu()
                
                for service in admin_repositories:
                    
                    submenu = wx.Menu()
                    
                    service_key = service.GetServiceKey()
                    
                    can_create_accounts = service.HasPermission( HC.CONTENT_TYPE_ACCOUNTS, HC.PERMISSION_ACTION_CREATE )
                    can_overrule_accounts = service.HasPermission( HC.CONTENT_TYPE_ACCOUNTS, HC.PERMISSION_ACTION_OVERRULE )
                    can_overrule_account_types = service.HasPermission( HC.CONTENT_TYPE_ACCOUNT_TYPES, HC.PERMISSION_ACTION_OVERRULE )
                    
                    if can_create_accounts:
                        
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'create new accounts', 'Create new account keys for this service.', self._GenerateNewAccounts, service_key )
                        
                    
                    if can_overrule_accounts:
                        
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'modify an account', 'Modify a specific account\'s type and expiration.', self._ModifyAccount, service_key )
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'get an account\'s info', 'Fetch information about an account from the service.', self._AccountInfo, service_key )
                        
                    
                    if can_overrule_accounts and service.GetServiceType() == HC.FILE_REPOSITORY:
                        
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'get an uploader\'s ip address', 'Fetch the ip address that uploaded a specific file, if the service knows it.', self._FetchIP, service_key )
                        
                    
                    if can_overrule_account_types:
                        
                        ClientGUIMenus.AppendSeparator( submenu )
                        
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'manage account types', 'Add, edit and delete account types for this service.', self._ManageAccountTypes, service_key )
                        
                    
                    ClientGUIMenus.AppendMenu( admin_menu, submenu, service.GetName() )
                    
                
                for service in server_admins:
                    
                    submenu = wx.Menu()
                    
                    service_key = service.GetServiceKey()
                    
                    can_create_accounts = service.HasPermission( HC.CONTENT_TYPE_ACCOUNTS, HC.PERMISSION_ACTION_CREATE )
                    can_overrule_accounts = service.HasPermission( HC.CONTENT_TYPE_ACCOUNTS, HC.PERMISSION_ACTION_OVERRULE )
                    can_overrule_account_types = service.HasPermission( HC.CONTENT_TYPE_ACCOUNT_TYPES, HC.PERMISSION_ACTION_OVERRULE )
                    
                    if can_create_accounts:
                        
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'create new accounts', 'Create new account keys for this service.', self._GenerateNewAccounts, service_key )
                        
                    
                    if can_overrule_accounts:
                        
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'modify an account', 'Modify a specific account\'s type and expiration.', self._ModifyAccount, service_key )
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'get an account\'s info', 'Fetch information about an account from the service.', self._AccountInfo, service_key )
                        
                    
                    if can_overrule_account_types:
                        
                        ClientGUIMenus.AppendSeparator( submenu )
                        
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'manage account types', 'Add, edit and delete account types for this service.', self._ManageAccountTypes, service_key )
                        
                    
                    can_overrule_services = service.HasPermission( HC.CONTENT_TYPE_SERVICES, HC.PERMISSION_ACTION_OVERRULE )
                    
                    if can_overrule_services:
                        
                        ClientGUIMenus.AppendSeparator( submenu )
                        
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'manage services', 'Add, edit, and delete this server\'s services.', self._ManageServer, service_key )
                        ClientGUIMenus.AppendMenuItem( self, submenu, 'make a backup', 'Command the server to temporarily pause and back up its database.', self._BackupService, service_key )
                        
                    
                    ClientGUIMenus.AppendMenu( admin_menu, submenu, service.GetName() )
                    
                
                ClientGUIMenus.AppendMenu( menu, admin_menu, 'administrate services' )
                
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'import repository update files', 'Add repository update files to the database.', self._ImportUpdateFiles )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage tag censorship', 'Set which tags you want to see from which services.', self._ManageTagCensorship )
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage tag siblings', 'Set certain tags to be automatically replaced with other tags.', self._ManageTagSiblings )
            ClientGUIMenus.AppendMenuItem( self, menu, 'manage tag parents', 'Set certain tags to be automatically added with other tags.', self._ManageTagParents )
            
            return ( menu, '&services', True )
            
        
        def help():
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'help', 'Open hydrus\'s local help in your web browser.', webbrowser.open, 'file://' + HC.HELP_DIR + '/index.html' )
            
            links = wx.Menu()
            
            site = ClientGUIMenus.AppendMenuBitmapItem( self, links, 'site', 'Open hydrus\'s website, which is mostly a mirror of the local help.', CC.GlobalBMPs.file_repository, webbrowser.open, 'https://hydrusnetwork.github.io/hydrus/' )
            site = ClientGUIMenus.AppendMenuBitmapItem( self, links, '8chan board', 'Open hydrus dev\'s 8chan board, where he makes release posts and other status updates. Much other discussion also occurs.', CC.GlobalBMPs.eight_chan, webbrowser.open, 'https://8ch.net/hydrus/index.html' )
            site = ClientGUIMenus.AppendMenuBitmapItem( self, links, 'twitter', 'Open hydrus dev\'s twitter, where he makes general progress updates and emergency notifications.', CC.GlobalBMPs.twitter, webbrowser.open, 'https://twitter.com/hydrusnetwork' )
            site = ClientGUIMenus.AppendMenuBitmapItem( self, links, 'tumblr', 'Open hydrus dev\'s tumblr, where he makes release posts and other status updates.', CC.GlobalBMPs.tumblr, webbrowser.open, 'http://hydrus.tumblr.com/' )
            site = ClientGUIMenus.AppendMenuBitmapItem( self, links, 'discord', 'Open a discord channel where many hydrus users congregate. Hydrus dev visits regularly.', CC.GlobalBMPs.discord, webbrowser.open, 'https://discord.gg/vy8CUB4' )
            site = ClientGUIMenus.AppendMenuBitmapItem( self, links, 'patreon', 'Open hydrus dev\'s patreon, which lets you support development.', CC.GlobalBMPs.patreon, webbrowser.open, 'https://www.patreon.com/hydrus_dev' )
            
            ClientGUIMenus.AppendMenu( menu, links, 'links' )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'changelog', 'Open hydrus\'s local changelog in your web browser.', webbrowser.open, 'file://' + HC.HELP_DIR + '/changelog.html' )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            dont_know = wx.Menu()
            
            ClientGUIMenus.AppendMenuItem( self, dont_know, 'just set up some repositories for me, please', 'This will add the hydrus dev\'s two repositories to your client.', self._AutoRepoSetup )
            
            ClientGUIMenus.AppendMenu( menu, dont_know, 'I don\'t know what I am doing' )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            currently_darkmode = self._new_options.GetString( 'current_colourset' ) == 'darkmode'
            
            ClientGUIMenus.AppendMenuCheckItem( self, menu, 'darkmode', 'Set the \'darkmode\' colourset on and off.', currently_darkmode, self.FlipDarkmode )
            
            check_manager = ClientGUICommon.CheckboxManagerOptions( 'advanced_mode' )
            
            current_value = check_manager.GetCurrentValue()
            func = check_manager.Invert
            
            ClientGUIMenus.AppendMenuCheckItem( self, menu, 'advanced mode', 'Turn on advanced menu options and buttons.', current_value, func )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            debug = wx.Menu()
            
            debug_modes = wx.Menu()
            
            ClientGUIMenus.AppendMenuCheckItem( self, debug_modes, 'force idle mode', 'Make the client consider itself idle and fire all maintenance routines right now. This may hang the gui for a while.', HG.force_idle_mode, self._SwitchBoolean, 'force_idle_mode' )
            ClientGUIMenus.AppendMenuCheckItem( self, debug_modes, 'no page limit mode', 'Let the user create as many pages as they want with no warnings or prohibitions.', HG.no_page_limit_mode, self._SwitchBoolean, 'no_page_limit_mode' )
            
            ClientGUIMenus.AppendMenu( debug, debug_modes, 'debug modes' )
            
            profile_modes = wx.Menu()
            
            ClientGUIMenus.AppendMenuCheckItem( self, profile_modes, 'db profile mode', 'Run detailed \'profiles\' on every database query and dump this information to the log (this is very useful for hydrus dev to have, if something is running slow for you!).', HG.db_profile_mode, self._SwitchBoolean, 'db_profile_mode' )
            ClientGUIMenus.AppendMenuCheckItem( self, profile_modes, 'menu profile mode', 'Run detailed \'profiles\' on menu actions.', HG.menu_profile_mode, self._SwitchBoolean, 'menu_profile_mode' )
            ClientGUIMenus.AppendMenuCheckItem( self, profile_modes, 'pubsub profile mode', 'Run detailed \'profiles\' on every internal publisher/subscriber message and dump this information to the log. This can hammer your log with dozens of large dumps every second. Don\'t run it unless you know you need to.', HG.pubsub_profile_mode, self._SwitchBoolean, 'pubsub_profile_mode' )
            ClientGUIMenus.AppendMenuCheckItem( self, profile_modes, 'ui timer profile mode', 'Run detailed \'profiles\' on every ui timer update. This will likely spam you!', HG.ui_timer_profile_mode, self._SwitchBoolean, 'ui_timer_profile_mode' )
            
            ClientGUIMenus.AppendMenu( debug, profile_modes, 'profile modes' )
            
            report_modes = wx.Menu()
            
            ClientGUIMenus.AppendMenuCheckItem( self, report_modes, 'callto report mode', 'Report whenever the thread pool is given a task.', HG.callto_report_mode, self._SwitchBoolean, 'callto_report_mode' )
            ClientGUIMenus.AppendMenuCheckItem( self, report_modes, 'daemon report mode', 'Have the daemons report whenever they fire their jobs.', HG.daemon_report_mode, self._SwitchBoolean, 'daemon_report_mode' )
            ClientGUIMenus.AppendMenuCheckItem( self, report_modes, 'db report mode', 'Have the db report query information, where supported.', HG.db_report_mode, self._SwitchBoolean, 'db_report_mode' )
            ClientGUIMenus.AppendMenuCheckItem( self, report_modes, 'gui report mode', 'Have the gui report inside information, where supported.', HG.gui_report_mode, self._SwitchBoolean, 'gui_report_mode' )
            ClientGUIMenus.AppendMenuCheckItem( self, report_modes, 'hover window report mode', 'Have the hover windows report their show/hide logic.', HG.hover_window_report_mode, self._SwitchBoolean, 'hover_window_report_mode' )
            ClientGUIMenus.AppendMenuCheckItem( self, report_modes, 'network report mode', 'Have the network engine report new jobs.', HG.network_report_mode, self._SwitchBoolean, 'network_report_mode' )
            
            ClientGUIMenus.AppendMenu( debug, report_modes, 'report modes' )
            
            ClientGUIMenus.AppendMenuItem( self, debug, 'make some popups', 'Throw some varied popups at the message manager, just to check it is working.', self._DebugMakeSomePopups )
            ClientGUIMenus.AppendMenuItem( self, debug, 'make a popup in five seconds', 'Throw a delayed popup at the message manager, giving you time to minimise or otherwise alter the client before it arrives.', self._controller.CallLater, 5, HydrusData.ShowText, 'This is a delayed popup message.' )
            ClientGUIMenus.AppendMenuItem( self, debug, 'force a gui layout now', 'Tell the gui to relayout--useful to test some gui bootup layout issues.', self.Layout )
            ClientGUIMenus.AppendMenuItem( self, debug, 'flush log', 'Command the log to write any buffered contents to hard drive.', HydrusData.DebugPrint, 'Flushing log' )
            ClientGUIMenus.AppendMenuItem( self, debug, 'print garbage', 'Print some information about the python garbage to the log.', self._DebugPrintGarbage )
            ClientGUIMenus.AppendMenuItem( self, debug, 'clear image rendering cache', 'Tell the image rendering system to forget all current images. This will often free up a bunch of memory immediately.', self._controller.ClearCaches )
            ClientGUIMenus.AppendMenuItem( self, debug, 'clear db service info cache', 'Delete all cached service info like total number of mappings or files, in case it has become desynchronised. Some parts of the gui may be laggy immediately after this as these numbers are recalculated.', self._DeleteServiceInfo )
            ClientGUIMenus.AppendMenuItem( self, debug, 'load whole db in disk cache', 'Contiguously read as much of the db as will fit into memory. This will massively speed up any subsequent big job.', self._controller.CallToThread, self._controller.Read, 'load_into_disk_cache' )
            ClientGUIMenus.AppendMenuItem( self, debug, 'save \'last session\' gui session', 'Make an immediate save of the \'last session\' gui session. Mostly for testing crashes, where last session is not saved correctly.', self._notebook.SaveGUISession, 'last session' )
            ClientGUIMenus.AppendMenuItem( self, debug, 'run and initialise server for testing', 'This will try to boot the server in your install folder and initialise it. This is mostly here for testing purposes.', self._AutoServerSetup )
            
            ClientGUIMenus.AppendMenu( menu, debug, 'debug' )
            
            ClientGUIMenus.AppendSeparator( menu )
            
            ClientGUIMenus.AppendMenuItem( self, menu, 'hardcoded shortcuts', 'Review some currently hardcoded shortcuts.', wx.MessageBox, CC.SHORTCUT_HELP )
            ClientGUIMenus.AppendMenuItem( self, menu, 'about', 'See this client\'s version and other information.', self._AboutWindow )
            
            return ( menu, '&help', True )
            
        
        if name == 'file': return file()
        elif name == 'undo': return undo()
        elif name == 'pages': return pages()
        elif name == 'database': return database()
        elif name == 'network': return network()
        elif name == 'pending': return pending()
        elif name == 'services': return services()
        elif name == 'help': return help()
        
    
    def _GenerateNewAccounts( self, service_key ):
        
        with ClientGUIDialogs.DialogGenerateNewAccounts( self, service_key ) as dlg: dlg.ShowModal()
        
    
    def _ImportFiles( self, paths = None ):
        
        if paths is None:
            
            paths = []
            
        
        ClientGUIDialogs.FrameInputLocalFiles( self, paths )
        
    
    def _ImportUpdateFiles( self ):
        
        def do_it( external_update_dir ):
            
            num_errors = 0
            
            filenames = os.listdir( external_update_dir )
            
            update_paths = [ os.path.join( external_update_dir, filename ) for filename in filenames ]
            
            update_paths = filter( os.path.isfile, update_paths )
            
            num_to_do = len( update_paths )
            
            if num_to_do == 0:
                
                wx.CallAfter( wx.MessageBox, 'No files in that directory!' )
                
                return
                
            
            job_key = ClientThreading.JobKey( cancellable = True )
            
            try:
                
                job_key.SetVariable( 'popup_title', 'importing updates' )
                HG.client_controller.pub( 'message', job_key )
                
                for ( i, update_path ) in enumerate( update_paths ):
                    
                    ( i_paused, should_quit ) = job_key.WaitIfNeeded()
                    
                    if should_quit:
                        
                        job_key.SetVariable( 'popup_text_1', 'Cancelled!' )
                        
                        return
                        
                    
                    try:
                        
                        with open( update_path, 'rb' ) as f:
                            
                            update_network_string = f.read()
                            
                        
                        update_network_string_hash = hashlib.sha256( update_network_string ).digest()
                        
                        try:
                            
                            update = HydrusSerialisable.CreateFromNetworkString( update_network_string )
                            
                        except:
                            
                            num_errors += 1
                            
                            HydrusData.Print( update_path + ' did not load correctly!' )
                            
                            continue
                            
                        
                        if isinstance( update, HydrusNetwork.DefinitionsUpdate ):
                            
                            mime = HC.APPLICATION_HYDRUS_UPDATE_DEFINITIONS
                            
                        elif isinstance( update, HydrusNetwork.ContentUpdate ):
                            
                            mime = HC.APPLICATION_HYDRUS_UPDATE_CONTENT
                            
                        else:
                            
                            num_errors += 1
                            
                            HydrusData.Print( update_path + ' was not an update!' )
                            
                            continue
                            
                        
                        self._controller.WriteSynchronous( 'import_update', update_network_string, update_network_string_hash, mime )
                        
                    finally:
                        
                        job_key.SetVariable( 'popup_text_1', HydrusData.ConvertValueRangeToPrettyString( i + 1, num_to_do ) )
                        job_key.SetVariable( 'popup_gauge_1', ( i, num_to_do ) )
                        
                    
                
                if num_errors == 0:
                    
                    job_key.SetVariable( 'popup_text_1', 'Done!' )
                    
                else:
                    
                    job_key.SetVariable( 'popup_text_1', 'Done with ' + HydrusData.ConvertIntToPrettyString( num_errors ) + ' errors (written to the log).' )
                    
                
            finally:
                
                job_key.DeleteVariable( 'popup_gauge_1' )
                
                job_key.Finish()
                
            
        
        message = 'This lets you manually import a directory of update files for your repositories. Any update files that match what your repositories are looking for will be automatically linked so they do not have to be downloaded.'
        
        wx.MessageBox( message )
        
        with wx.DirDialog( self, 'Select location.' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_OK:
                
                path = HydrusData.ToUnicode( dlg.GetPath() )
                
                self._controller.CallToThread( do_it, path )
                
            
        
    
    def _InitialiseMenubar( self ):
        
        self._menubar = wx.MenuBar()
        
        self._menu_updater = ClientGUICommon.ThreadToGUIUpdater( self._menubar, self.RefreshMenu )
        self._dirty_menus = set()
        
        self.SetMenuBar( self._menubar )
        
        for name in MENU_ORDER:
            
            ( menu, label, show ) = self._GenerateMenuInfo( name )
            
            if show:
                
                self._menubar.Append( menu, label )
                
            
            self._menus[ name ] = ( menu, label, show )
            
        
    
    def _InitialiseSession( self ):
        
        default_gui_session = HC.options[ 'default_gui_session' ]
        
        existing_session_names = self._controller.Read( 'serialisable_names', HydrusSerialisable.SERIALISABLE_TYPE_GUI_SESSION )
        
        cannot_load_from_db = default_gui_session not in existing_session_names
        
        load_a_blank_page = HC.options[ 'default_gui_session' ] == 'just a blank page' or cannot_load_from_db
        
        if not load_a_blank_page:
            
            if self._controller.LastShutdownWasBad():
                
                # this can be upgraded to a nicer checkboxlist dialog to select pages or w/e
                
                message = 'It looks like the last instance of the client did not shut down cleanly.'
                message += os.linesep * 2
                message += 'Would you like to try loading your default session \'' + default_gui_session + '\', or just a blank page?'
                
                with ClientGUIDialogs.DialogYesNo( self, message, title = 'Previous shutdown was bad', yes_label = 'try to load the default session', no_label = 'just load a blank page' ) as dlg:
                    
                    if dlg.ShowModal() == wx.ID_NO:
                        
                        load_a_blank_page = True
                        
                    
                
            
        
        if load_a_blank_page:
            
            self._notebook.NewPageQuery( CC.LOCAL_FILE_SERVICE_KEY, on_deepest_notebook = True )
            
        else:
            
            self._notebook.LoadGUISession( default_gui_session )
            
        
        last_session_save_period_minutes = self._controller.new_options.GetInteger( 'last_session_save_period_minutes' )
        
        self._controller.CallLaterWXSafe( self, last_session_save_period_minutes * 60, self.SaveLastSession )
        
    
    def _ManageAccountTypes( self, service_key ):
        
        title = 'manage account types'
        
        with ClientGUITopLevelWindows.DialogManage( self, title ) as dlg:
            
            panel = ClientGUIScrolledPanelsManagement.ManageAccountTypesPanel( dlg, service_key )
            
            dlg.SetPanel( panel )
            
            dlg.ShowModal()
            
        
    
    def _ManageBoorus( self ):
        
        with ClientGUIDialogsManage.DialogManageBoorus( self ) as dlg: dlg.ShowModal()
        
    
    def _ManageExportFolders( self ):
        
        original_pause_status = HC.options[ 'pause_export_folders_sync' ]
        
        HC.options[ 'pause_export_folders_sync' ] = True
        
        try:
            
            with ClientGUIDialogsManage.DialogManageExportFolders( self ) as dlg:
                
                dlg.ShowModal()
                
            
        finally:
            
            HC.options[ 'pause_export_folders_sync' ] = original_pause_status
            
        
    
    def _ManageImportFolders( self ):
        
        def wx_do_it():
            
            if not self:
                
                return
                
            
            with ClientGUIDialogsManage.DialogManageImportFolders( self ) as dlg:
                
                dlg.ShowModal()
                
            
        
        def THREAD_do_it( controller ):
            
            original_pause_status = controller.options[ 'pause_import_folders_sync' ]
            
            controller.options[ 'pause_import_folders_sync' ] = True
            
            try:
                
                if HG.import_folders_running:
                    
                    job_key = ClientThreading.JobKey()
                    
                    try:
                        
                        job_key.SetVariable( 'popup_text_1', 'Waiting for import folders to finish.' )
                        
                        controller.pub( 'message', job_key )
                        
                        while HG.import_folders_running:
                            
                            time.sleep( 0.1 )
                            
                            if HG.view_shutdown:
                                
                                return
                                
                            
                        
                    finally:
                        
                        job_key.Delete()
                        
                    
                
                controller.CallBlockingToWx( wx_do_it )
                
            finally:
                
                controller.options[ 'pause_import_folders_sync' ] = original_pause_status
                
                controller.pub( 'notify_new_import_folders' )
                
            
        
        self._controller.CallToThread( THREAD_do_it, self._controller )
        
    
    def _ManageNetworkHeaders( self ):
        
        title = 'manage network headers'
        
        with ClientGUITopLevelWindows.DialogEdit( self, title ) as dlg:
            
            domain_manager = self._controller.network_engine.domain_manager
            
            network_contexts_to_custom_header_dicts = domain_manager.GetNetworkContextsToCustomHeaderDicts()
            
            panel = ClientGUIScrolledPanelsEdit.EditNetworkContextCustomHeadersPanel( dlg, network_contexts_to_custom_header_dicts )
            
            dlg.SetPanel( panel )
            
            if dlg.ShowModal() == wx.ID_OK:
                
                network_contexts_to_custom_header_dicts = panel.GetValue()
                
                domain_manager.SetNetworkContextsToCustomHeaderDicts( network_contexts_to_custom_header_dicts )
                
            
        
    
    def _ManageOptions( self ):
        
        title = 'manage options'
        frame_key = 'manage_options_dialog'
        
        with ClientGUITopLevelWindows.DialogManage( self, title, frame_key ) as dlg:
            
            panel = ClientGUIScrolledPanelsManagement.ManageOptionsPanel( dlg )
            
            dlg.SetPanel( panel )
            
            dlg.ShowModal()
            
        
        self._controller.pub( 'wake_daemons' )
        self._controller.gui.SetStatusBarDirty()
        self._controller.pub( 'refresh_page_name' )
        
    
    def _ManageParsers( self ):
        
        title = 'manage parsers'
        
        with ClientGUITopLevelWindows.DialogEdit( self, title ) as dlg:
            
            domain_manager = self._controller.network_engine.domain_manager
            
            parsers = domain_manager.GetParsers()
            
            panel = ClientGUIParsing.EditParsersPanel( dlg, parsers )
            
            dlg.SetPanel( panel )
            
            if dlg.ShowModal() == wx.ID_OK:
                
                parsers = panel.GetValue()
                
                domain_manager.SetParsers( parsers )
                
            
        
    
    def _ManageParsingScripts( self ):
        
        title = 'manage parsing scripts'
        
        with ClientGUITopLevelWindows.DialogManage( self, title ) as dlg:
            
            panel = ClientGUIParsing.ManageParsingScriptsPanel( dlg )
            
            dlg.SetPanel( panel )
            
            dlg.ShowModal()
            
        
    
    def _ManagePixivAccount( self ):
        
        with ClientGUIDialogsManage.DialogManagePixivAccount( self ) as dlg: dlg.ShowModal()
        
    
    def _ManageServer( self, service_key ):
        
        title = 'manage server services'
        
        with ClientGUITopLevelWindows.DialogManage( self, title ) as dlg:
            
            panel = ClientGUIScrolledPanelsManagement.ManageServerServicesPanel( dlg, service_key )
            
            dlg.SetPanel( panel )
            
            dlg.ShowModal()
            
        
    
    def _ManageServices( self ):
        
        original_pause_status = HC.options[ 'pause_repo_sync' ]
        
        HC.options[ 'pause_repo_sync' ] = True
        
        try:
            
            title = 'manage services'
            
            with ClientGUITopLevelWindows.DialogManage( self, title ) as dlg:
                
                panel = ClientGUIScrolledPanelsManagement.ManageClientServicesPanel( dlg )
                
                dlg.SetPanel( panel )
                
                dlg.ShowModal()
                
            
        finally:
            
            HC.options[ 'pause_repo_sync' ] = original_pause_status
            
        
    
    def _ManageShortcuts( self ):
        
        with ClientGUITopLevelWindows.DialogManage( self, 'manage shortcuts' ) as dlg:
            
            panel = ClientGUIScrolledPanelsManagement.ManageShortcutsPanel( dlg )
            
            dlg.SetPanel( panel )
            
            dlg.ShowModal()
            
        
    
    def _ManageSubscriptions( self ):
        
        def wx_do_it():
            
            if not self:
                
                return
                
            
            title = 'manage subscriptions'
            frame_key = 'manage_subscriptions_dialog'
            
            with ClientGUITopLevelWindows.DialogManage( self, title, frame_key ) as dlg:
                
                panel = ClientGUIScrolledPanelsManagement.ManageSubscriptionsPanel( dlg )
                
                dlg.SetPanel( panel )
                
                dlg.ShowModal()
                
            
        
        def THREAD_do_it( controller ):
            
            original_pause_status = controller.options[ 'pause_subs_sync' ]
            
            controller.options[ 'pause_subs_sync' ] = True
            
            try:
                
                if HG.subscriptions_running:
                    
                    job_key = ClientThreading.JobKey()
                    
                    try:
                        
                        job_key.SetVariable( 'popup_text_1', 'Waiting for subs to finish.' )
                        
                        controller.pub( 'message', job_key )
                        
                        while HG.subscriptions_running:
                            
                            time.sleep( 0.1 )
                            
                            if HG.view_shutdown:
                                
                                return
                                
                            
                        
                    finally:
                        
                        job_key.Delete()
                        
                    
                
                controller.CallBlockingToWx( wx_do_it )
                
            finally:
                
                controller.options[ 'pause_subs_sync' ] = original_pause_status
                
                controller.pub( 'notify_new_subscriptions' )
                
            
        
        self._controller.CallToThread( THREAD_do_it, self._controller )
        
    
    def _ManageTagCensorship( self ):
        
        with ClientGUIDialogsManage.DialogManageTagCensorship( self ) as dlg: dlg.ShowModal()
        
    
    def _ManageTagParents( self ):
        
        with ClientGUIDialogsManage.DialogManageTagParents( self ) as dlg: dlg.ShowModal()
        
    
    def _ManageTagSiblings( self ):
        
        with ClientGUIDialogsManage.DialogManageTagSiblings( self ) as dlg: dlg.ShowModal()
        
    
    def _ManageURLMatches( self ):
        
        title = 'manage url classes'
        
        with ClientGUITopLevelWindows.DialogEdit( self, title ) as dlg:
            
            domain_manager = self._controller.network_engine.domain_manager
            
            url_matches = domain_manager.GetURLMatches()
            
            panel = ClientGUIScrolledPanelsEdit.EditURLMatchesPanel( dlg, url_matches )
            
            dlg.SetPanel( panel )
            
            if dlg.ShowModal() == wx.ID_OK:
                
                url_matches = panel.GetValue()
                
                domain_manager.SetURLMatches( url_matches )
                
            
        
    
    def _ManageURLMatchLinks( self ):
        
        title = 'manage url class links'
        
        with ClientGUITopLevelWindows.DialogEdit( self, title ) as dlg:
            
            domain_manager = self._controller.network_engine.domain_manager
            
            url_matches = domain_manager.GetURLMatches()
            parsers = domain_manager.GetParsers()
            
            ( url_match_keys_to_display, url_match_keys_to_parser_keys ) = domain_manager.GetURLMatchLinks()
            
            panel = ClientGUIScrolledPanelsEdit.EditURLMatchLinksPanel( dlg, self._controller.network_engine, url_matches, parsers, url_match_keys_to_display, url_match_keys_to_parser_keys )
            
            dlg.SetPanel( panel )
            
            if dlg.ShowModal() == wx.ID_OK:
                
                ( url_match_keys_to_display, url_match_keys_to_parser_keys ) = panel.GetValue()
                
                domain_manager.SetURLMatchLinks( url_match_keys_to_display, url_match_keys_to_parser_keys )
                
            
        
    
    def _ManageUPnP( self ):
        
        with ClientGUIDialogsManage.DialogManageUPnP( self ) as dlg: dlg.ShowModal()
        
    
    def _MigrateDatabase( self ):
        
        with ClientGUITopLevelWindows.DialogNullipotent( self, 'migrate database' ) as dlg:
            
            panel = ClientGUIScrolledPanelsReview.MigrateDatabasePanel( dlg, self._controller )
            
            dlg.SetPanel( panel )
            
            dlg.ShowModal()
            
        
    
    def _ModifyAccount( self, service_key ):
        
        wx.MessageBox( 'this does not work yet!' )
        
        return
        
        service = self._controller.services_manager.GetService( service_key )
        
        with ClientGUIDialogs.DialogTextEntry( self, 'Enter the account key for the account to be modified.' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_OK:
                
                try:
                    
                    account_key = dlg.GetValue().decode( 'hex' )
                    
                except:
                    
                    wx.MessageBox( 'Could not parse that account key' )
                    
                    return
                    
                
                subject_account = 'blah' # fetch account from service
                
                with ClientGUIDialogs.DialogModifyAccounts( self, service_key, [ subject_account ] ) as dlg2: dlg2.ShowModal()
                
            
        
    
    def _OpenDBFolder( self ):
        
        HydrusPaths.LaunchDirectory( self._controller.GetDBDir() )
        
    
    def _OpenExportFolder( self ):
        
        export_path = ClientExporting.GetExportPath()
        
        HydrusPaths.LaunchDirectory( export_path )
        
    
    def _OpenInstallFolder( self ):
        
        HydrusPaths.LaunchDirectory( HC.BASE_DIR )
        
    
    def _PauseSync( self, sync_type ):
        
        if sync_type == 'repo':
            
            HC.options[ 'pause_repo_sync' ] = not HC.options[ 'pause_repo_sync' ]
            
            self._controller.pub( 'notify_restart_repo_sync_daemon' )
            
        elif sync_type == 'subs':
            
            HC.options[ 'pause_subs_sync' ] = not HC.options[ 'pause_subs_sync' ]
            
            self._controller.pub( 'notify_restart_subs_sync_daemon' )
            
        elif sync_type == 'export_folders':
            
            HC.options[ 'pause_export_folders_sync' ] = not HC.options[ 'pause_export_folders_sync' ]
            
            self._controller.pub( 'notify_restart_export_folders_daemon' )
            
        elif sync_type == 'import_folders':
            
            HC.options[ 'pause_import_folders_sync' ] = not HC.options[ 'pause_import_folders_sync' ]
            
            self._controller.pub( 'notify_restart_import_folders_daemon' )
            
        
        self._controller.Write( 'save_options', HC.options )
        
    
    def _ProcessApplicationCommand( self, command ):
        
        command_processed = True
        
        command_type = command.GetCommandType()
        data = command.GetData()
        
        if command_type == CC.APPLICATION_COMMAND_TYPE_SIMPLE:
            
            action = data
            
            if action == 'refresh':
                
                self._Refresh()
                
            elif action == 'new_page':
                
                self._notebook.ChooseNewPageForDeepestNotebook()
                
            if action == 'close_page':
                
                self._notebook.CloseCurrentPage()
                
            elif action == 'unclose_page':
                
                self._UnclosePage()
                
            elif action == 'check_all_import_folders':
                
                self._CheckImportFolder()
                
            elif action == 'flip_darkmode':
                
                self.FlipDarkmode()
                
            elif action == 'show_hide_splitters':
                
                self._ShowHideSplitters()
                
            elif action == 'synchronised_wait_switch':
                
                self._SetSynchronisedWait()
                
            elif action == 'set_media_focus':
                
                self._SetMediaFocus()
                
            elif action == 'set_search_focus':
                
                self._SetSearchFocus()
                
            elif action == 'redo':
                
                self._controller.pub( 'redo' )
                
            elif action == 'undo':
                
                self._controller.pub( 'undo' )
                
            else:
                
                command_processed = False
                
            
        else:
            
            command_processed = False
            
        
        return command_processed
        
    
    def _ProcessShortcut( self, shortcut ):
        
        shortcut_processed = False
        
        command = HG.client_controller.GetCommandFromShortcut( [ 'main_gui' ], shortcut )
        
        if command is not None:
            
            command_processed = self._ProcessApplicationCommand( command )
            
            if command_processed:
                
                shortcut_processed = True
                
            
        
        return shortcut_processed
        
    
    def _Refresh( self ):
        
        page = self._notebook.GetCurrentMediaPage()
        
        if page is not None:
            
            page.RefreshQuery()
            
        
    
    def _RefreshStatusBar( self ):
        
        if not self._notebook or not self._statusbar:
            
            return
            
        
        page = self._notebook.GetCurrentMediaPage()
        
        if page is None:
            
            media_status = ''
            
        else:
            
            media_status = page.GetPrettyStatus()
            
        
        if self._controller.CurrentlyIdle():
            
            idle_status = 'idle'
            
        else:
            
            idle_status = ''
            
        
        if self._controller.SystemBusy():
            
            busy_status = 'system busy'
            
        else:
            
            busy_status = ''
            
        
        ( db_status, job_name ) = HG.client_controller.GetDBStatus()
        
        self._statusbar.SetToolTip( job_name )
        
        self._statusbar.SetStatusText( media_status, 0 )
        self._statusbar.SetStatusText( idle_status, 2 )
        self._statusbar.SetStatusText( busy_status, 3 )
        self._statusbar.SetStatusText( db_status, 4 )
        
    
    def _RegenerateACCache( self ):
        
        message = 'This will delete and then recreate the entire autocomplete cache. This is useful if miscounting has somehow occured.'
        message += os.linesep * 2
        message += 'If you have a lot of tags and files, it can take a long time, during which the gui may hang.'
        message += os.linesep * 2
        message += 'If you do not have a specific reason to run this, it is pointless.'
        
        with ClientGUIDialogs.DialogYesNo( self, message, yes_label = 'do it', no_label = 'forget it' ) as dlg:
            
            result = dlg.ShowModal()
            
            if result == wx.ID_YES:
                
                self._controller.Write( 'regenerate_ac_cache' )
                
            
        
    
    def _RegenerateSimilarFilesPhashes( self ):
        
        message = 'This will schedule all similar files \'phash\' metadata to be regenerated. This is a very expensive operation that will occur in future idle time.'
        message += os.linesep * 2
        message += 'This ultimately requires a full read for all valid files. It is a large investment of CPU and HDD time.'
        message += os.linesep * 2
        message += 'Do not run this unless you know your phashes need to be regenerated.'
        
        with ClientGUIDialogs.DialogYesNo( self, message, yes_label = 'do it', no_label = 'forget it' ) as dlg:
            
            result = dlg.ShowModal()
            
            if result == wx.ID_YES:
                
                self._controller.Write( 'schedule_full_phash_regen' )
                
            
        
    
    def _RegenerateSimilarFilesTree( self ):
        
        message = 'This will delete and then recreate the similar files search tree. This is useful if it has somehow become unbalanced and similar files searches are running slow.'
        message += os.linesep * 2
        message += 'If you have a lot of files, it can take a little while, during which the gui may hang.'
        message += os.linesep * 2
        message += 'If you do not have a specific reason to run this, it is pointless.'
        
        with ClientGUIDialogs.DialogYesNo( self, message, yes_label = 'do it', no_label = 'forget it' ) as dlg:
            
            result = dlg.ShowModal()
            
            if result == wx.ID_YES:
                
                self._controller.Write( 'regenerate_similar_files' )
                
            
        
    
    def _RegenerateThumbnails( self ):
        
        client_files_manager = self._controller.client_files_manager
        
        text = 'This will rebuild all your thumbnails from the original files. You probably only want to do this if you experience thumbnail errors. If you have a lot of files, it will take some time. A popup message will show its progress.'
        text += os.linesep * 2
        text += 'You can choose to only regenerate missing thumbnails, which is useful if you are rebuilding a fractured database, or you can force a complete refresh of all thumbnails, which is useful if some have been corrupted by a faulty hard drive.'
        text += os.linesep * 2
        text += 'Files and thumbnails will be inaccessible while this occurs, so it is best to leave the client alone until it is done.'
        
        with ClientGUIDialogs.DialogYesNo( self, text, yes_label = 'only do missing', no_label = 'force all' ) as dlg:
            
            result = dlg.ShowModal()
            
            if result == wx.ID_YES:
                
                self._controller.CallToThread( client_files_manager.RegenerateThumbnails, only_do_missing = True )
                
            elif result == wx.ID_NO:
                
                self._controller.CallToThread( client_files_manager.RegenerateThumbnails )
                
            
        
    
    def _ReviewBandwidth( self ):
        
        frame = ClientGUITopLevelWindows.FrameThatTakesScrollablePanel( self, 'review bandwidth' )
        
        panel = ClientGUIScrolledPanelsReview.ReviewAllBandwidthPanel( frame, self._controller )
        
        frame.SetPanel( panel )
        
    
    def _ReviewServices( self ):
        
        frame = ClientGUITopLevelWindows.FrameThatTakesScrollablePanel( self, self._controller.PrepStringForDisplay( 'Review Services' ), 'review_services' )
        
        panel = ClientGUIScrolledPanelsReview.ReviewServicesPanel( frame, self._controller )
        
        frame.SetPanel( panel )
        
    
    def _SetPassword( self ):
        
        message = '''You can set a password to be asked for whenever the client starts.

Though not foolproof by any means, it will stop noobs from easily seeing your files if you leave your machine unattended.

Do not ever forget your password! If you do, you'll have to manually insert a yaml-dumped python dictionary into a sqlite database or recompile from source to regain easy access. This is not trivial.

The password is cleartext here but obscured in the entry dialog. Enter a blank password to remove.'''
        
        with ClientGUIDialogs.DialogTextEntry( self, message, allow_blank = True ) as dlg:
            
            if dlg.ShowModal() == wx.ID_OK:
                
                password = dlg.GetValue()
                
                if password == '': password = None
                
                self._controller.Write( 'set_password', password )
                
            
        
    
    def _SetMediaFocus( self ):
        
        page = self._notebook.GetCurrentMediaPage()
        
        if page is not None:
            
            page.SetMediaFocus()
            
        
    
    def _SetSearchFocus( self ):
        
        page = self._notebook.GetCurrentMediaPage()
        
        if page is not None:
            
            page.SetSearchFocus()
            
        
    
    def _SetSynchronisedWait( self ):
        
        page = self._notebook.GetCurrentMediaPage()
        
        if page is not None:
            
            page.SetSynchronisedWait()
            
        
    
    def _SetupBackupPath( self ):
        
        backup_intro = 'Everything in your client is stored in the database, which consists of a handful of .db files and a single subdirectory that contains all your media files. It is a very good idea to maintain a regular backup schedule--to save from hard drive failure, serious software fault, accidental deletion, or any other unexpected problem. It sucks to lose all your work, so make sure it can\'t happen!'
        backup_intro += os.linesep * 2
        backup_intro += 'If you prefer to create a manual backup with an external program like FreeFileSync, then please cancel out of the dialog after this and set up whatever you like, but if you would rather a simple solution, simply select a directory and the client will remember it as the designated backup location. Creating or updating your backup can be triggered at any time from the database menu.'
        backup_intro += os.linesep * 2
        backup_intro += 'An ideal backup location is initially empty and on a different hard drive.'
        backup_intro += os.linesep * 2
        backup_intro += 'If you have a large database (100,000+ files) or a slow hard drive, creating the initial backup may take a long time--perhaps an hour or more--but updating an existing backup should only take a couple of minutes (since the client only has to copy new or modified files). Try to update your backup every week!'
        backup_intro += os.linesep * 2
        backup_intro += 'If you would like some more info on making or restoring backups, please consult the help\'s \'installing and updating\' page.'
        
        wx.MessageBox( backup_intro )
        
        with wx.DirDialog( self, 'Select backup location.' ) as dlg:
            
            if dlg.ShowModal() == wx.ID_OK:
                
                path = HydrusData.ToUnicode( dlg.GetPath() )
                
                if path == '':
                    
                    path = None
                    
                
                if path == self._controller.GetDBDir():
                    
                    wx.MessageBox( 'That directory is your current database directory! You cannot backup to the same location you are backing up from!' )
                    
                    return
                    
                
                if os.path.exists( path ):
                    
                    filenames = os.listdir( path )
                    
                    num_files = len( filenames )
                    
                    if num_files == 0:
                        
                        extra_info = 'It looks currently empty, which is great--there is no danger of anything being overwritten.'
                        
                    elif 'client.db' in filenames:
                        
                        extra_info = 'It looks like a client database already exists in the location--be certain that it is ok to overwrite it.'
                        
                    else:
                        
                        extra_info = 'It seems to have some files already in it--be careful and make sure you chose the correct location.'
                        
                    
                else:
                    
                    extra_info = 'The path does not exist yet--it will be created when you make your first backup.'
                    
                
                text = 'You chose "' + path + '". Here is what I understand about it:'
                text += os.linesep * 2
                text += extra_info
                text += os.linesep * 2
                text += 'Are you sure this is the correct directory?'
                
                with ClientGUIDialogs.DialogYesNo( self, text ) as dlg_yn:
                    
                    if dlg_yn.ShowModal() == wx.ID_YES:
                        
                        self._new_options.SetNoneableString( 'backup_path', path )
                        
                        text = 'Would you like to create your backup now?'
                        
                        with ClientGUIDialogs.DialogYesNo( self, text ) as dlg_yn_2:
                            
                            if dlg_yn_2.ShowModal() == wx.ID_YES:
                                
                                self._BackupDatabase()
                                
                            
                        
                    
                
            
        
    
    def _ShowHideSplitters( self ):
        
        page = self._notebook.GetCurrentMediaPage()
        
        if page is not None:
            
            page.ShowHideSplit()
            
        
    
    def _StartIPFSDownload( self ):
        
        ipfs_services = self._controller.services_manager.GetServices( ( HC.IPFS, ) )
        
        if len( ipfs_services ) > 0:
            
            if len( ipfs_services ) == 1:
                
                ( service, ) = ipfs_services
                
            else:
                
                list_of_tuples = [ ( service.GetName(), service ) for service in ipfs_services ]
                
                with ClientGUIDialogs.DialogSelectFromList( self, 'Select which IPFS Daemon', list_of_tuples ) as dlg:
                    
                    if dlg.ShowModal() == wx.ID_OK:
                        
                        service = dlg.GetChoice()
                        
                    else:
                        
                        return
                        
                    
                
            
            with ClientGUIDialogs.DialogTextEntry( self, 'Enter multihash to download.' ) as dlg:
                
                result = dlg.ShowModal()
                
                if result == wx.ID_OK:
                    
                    multihash = dlg.GetValue()
                    
                    service.ImportFile( multihash )
                    
                
            
        
    
    def _StartYoutubeDownload( self ):
        
        with ClientGUIDialogs.DialogTextEntry( self, 'Enter YouTube URL.' ) as dlg:
            
            result = dlg.ShowModal()
            
            if result == wx.ID_OK:
                
                url = dlg.GetValue()
                
                info = ClientDownloading.GetYoutubeFormats( url )
                
                with ClientGUIDialogs.DialogSelectYoutubeURL( self, info ) as select_dlg: select_dlg.ShowModal()
                
            
        
    
    def _SwitchBoolean( self, name ):
        
        if name == 'callto_report_mode':
            
            HG.callto_report_mode = not HG.callto_report_mode
            
        elif name == 'daemon_report_mode':
            
            HG.daemon_report_mode = not HG.daemon_report_mode
            
        elif name == 'db_report_mode':
            
            HG.db_report_mode = not HG.db_report_mode
            
        elif name == 'db_profile_mode':
            
            HG.db_profile_mode = not HG.db_profile_mode
            
        elif name == 'gui_report_mode':
            
            HG.gui_report_mode = not HG.gui_report_mode
            
        elif name == 'hover_window_report_mode':
            
            HG.hover_window_report_mode = not HG.hover_window_report_mode
            
        elif name == 'menu_profile_mode':
            
            HG.menu_profile_mode = not HG.menu_profile_mode
            
        elif name == 'network_report_mode':
            
            HG.network_report_mode = not HG.network_report_mode
            
        elif name == 'pubsub_profile_mode':
            
            HG.pubsub_profile_mode = not HG.pubsub_profile_mode
            
        elif name == 'ui_timer_profile_mode':
            
            HG.ui_timer_profile_mode = not HG.ui_timer_profile_mode
            
            if HG.ui_timer_profile_mode:
                
                HydrusData.ShowText( 'ui timer profile mode activated' )
                
            else:
                
                HydrusData.ShowText( 'ui timer profile mode deactivated' )
                
            
        elif name == 'force_idle_mode':
            
            HG.force_idle_mode = not HG.force_idle_mode
            
            self._controller.pub( 'wake_daemons' )
            self._controller.gui.SetStatusBarDirty()
            
        elif name == 'no_page_limit_mode':
            
            HG.no_page_limit_mode = not HG.no_page_limit_mode
            
        
    
    def _UnclosePage( self, closed_page_index = None ):
        
        if closed_page_index is None:
            
            if len( self._closed_pages ) == 0:
                
                return
                
            
            closed_page_index = 0
            
        
        with self._lock:
            
            ( time_closed, page ) = self._closed_pages.pop( closed_page_index )
            
            self._closed_page_keys.discard( page.GetPageKey() )
            
        
        self._controller.pub( 'notify_page_unclosed', page )
        
        self._controller.pub( 'notify_new_undo' )
        
        self._controller.pub( 'notify_new_pages' )
        
    
    def _UploadPending( self, service_key ):
        
        self._controller.CallToThread( self._THREADUploadPending, service_key )
        
    
    def _VacuumDatabase( self ):
        
        text = 'This will rebuild the database, rewriting all indices and tables to be contiguous and optimising most operations. It typically happens automatically every few days, but you can force it here. If you have a large database, it will take a few minutes, during which your gui may hang. A popup message will show its status.'
        text += os.linesep * 2
        text += 'A \'soft\' vacuum will only reanalyze those databases that are due for a check in the normal db maintenance cycle. If nothing is due, it will return immediately.'
        text += os.linesep * 2
        text += 'A \'full\' vacuum will immediately force a vacuum for the entire database. This can take substantially longer.'
        
        with ClientGUIDialogs.DialogYesNo( self, text, title = 'Choose how thorough your vacuum will be.', yes_label = 'soft', no_label = 'full' ) as dlg:
            
            result = dlg.ShowModal()
            
            if result == wx.ID_YES:
                
                self._controller.Write( 'vacuum' )
                
            elif result == wx.ID_NO:
                
                self._controller.Write( 'vacuum', force_vacuum = True )
                
            
        
    
    def _THREADSyncToTagArchive( self, hta_path, tag_service_key, file_service_key, adding, namespaces, hashes = None ):
        
        if hashes is not None:
            
            hashes = set( hashes )
            
        
        job_key = ClientThreading.JobKey( pausable = True, cancellable = True )
        
        try:
            
            hta = HydrusTagArchive.HydrusTagArchive( hta_path )
            
            job_key.SetVariable( 'popup_title', 'syncing to tag archive ' + hta.GetName() )
            job_key.SetVariable( 'popup_text_1', 'preparing' )
            
            self._controller.pub( 'message', job_key )
            
            hydrus_hashes = []
            
            hash_type = hta.GetHashType()
            
            total_num_hta_hashes = 0
            
            for chunk_of_hta_hashes in HydrusData.SplitIteratorIntoChunks( hta.IterateHashes(), 1000 ):
                
                while job_key.IsPaused() or job_key.IsCancelled():
                    
                    time.sleep( 0.1 )
                    
                    if job_key.IsCancelled():
                        
                        job_key.SetVariable( 'popup_text_1', 'cancelled' )
                        
                        HydrusData.Print( job_key.ToString() )
                        
                        return
                        
                    
                
                if hash_type == HydrusTagArchive.HASH_TYPE_SHA256:
                    
                    chunk_of_hydrus_hashes = chunk_of_hta_hashes
                    
                else:
                    
                    if hash_type == HydrusTagArchive.HASH_TYPE_MD5: given_hash_type = 'md5'
                    elif hash_type == HydrusTagArchive.HASH_TYPE_SHA1: given_hash_type = 'sha1'
                    elif hash_type == HydrusTagArchive.HASH_TYPE_SHA512: given_hash_type = 'sha512'
                    
                    chunk_of_hydrus_hashes = self._controller.Read( 'file_hashes', chunk_of_hta_hashes, given_hash_type, 'sha256' )
                    
                
                if file_service_key != CC.COMBINED_FILE_SERVICE_KEY:
                    
                    chunk_of_hydrus_hashes = self._controller.Read( 'filter_hashes', chunk_of_hydrus_hashes, file_service_key )
                    
                
                if hashes is not None:
                    
                    chunk_of_hydrus_hashes = [ hash for hash in chunk_of_hydrus_hashes if hash in hashes ]
                    
                
                hydrus_hashes.extend( chunk_of_hydrus_hashes )
                
                total_num_hta_hashes += len( chunk_of_hta_hashes )
                
                job_key.SetVariable( 'popup_text_1', 'matched ' + HydrusData.ConvertValueRangeToPrettyString( len( hydrus_hashes ), total_num_hta_hashes ) + ' files' )
                
                HG.client_controller.WaitUntilViewFree()
                
            
            del hta
            
            total_num_processed = 0
            
            for chunk_of_hydrus_hashes in HydrusData.SplitListIntoChunks( hydrus_hashes, 50 ):
        
                while job_key.IsPaused() or job_key.IsCancelled():
                    
                    time.sleep( 0.1 )
                    
                    if job_key.IsCancelled():
                        
                        job_key.SetVariable( 'popup_text_1', 'cancelled' )
                        
                        HydrusData.Print( job_key.ToString() )
                        
                        return
                        
                    
                
                self._controller.WriteSynchronous( 'sync_hashes_to_tag_archive', chunk_of_hydrus_hashes, hta_path, tag_service_key, adding, namespaces )
                
                total_num_processed += len( chunk_of_hydrus_hashes )
                
                job_key.SetVariable( 'popup_text_1', 'synced ' + HydrusData.ConvertValueRangeToPrettyString( total_num_processed, len( hydrus_hashes ) ) + ' files' )
                job_key.SetVariable( 'popup_gauge_1', ( total_num_processed, len( hydrus_hashes ) ) )
                
                HG.client_controller.WaitUntilViewFree()
                
            
            job_key.DeleteVariable( 'popup_gauge_1' )
            job_key.SetVariable( 'popup_text_1', 'done!' )
            
            job_key.Finish()
            
        except Exception as e:
            
            HydrusData.ShowException( e )
            
            job_key.Cancel()
            
        
    
    def _THREADUploadPending( self, service_key ):
        
        service = self._controller.services_manager.GetService( service_key )
        
        service_name = service.GetName()
        service_type = service.GetServiceType()
        
        nums_pending = self._controller.Read( 'nums_pending' )
        
        info = nums_pending[ service_key ]
        
        initial_num_pending = sum( info.values() )
        
        result = self._controller.Read( 'pending', service_key )
        
        try:
            
            job_key = ClientThreading.JobKey( pausable = True, cancellable = True )
            
            job_key.SetVariable( 'popup_title', 'uploading pending to ' + service_name )
            
            self._controller.pub( 'message', job_key )
            
            while result is not None:
                
                nums_pending = self._controller.Read( 'nums_pending' )
                
                info = nums_pending[ service_key ]
                
                remaining_num_pending = sum( info.values() )
                done_num_pending = initial_num_pending - remaining_num_pending
                
                job_key.SetVariable( 'popup_text_1', 'uploading to ' + service_name + ': ' + HydrusData.ConvertValueRangeToPrettyString( done_num_pending, initial_num_pending ) )
                job_key.SetVariable( 'popup_gauge_1', ( done_num_pending, initial_num_pending ) )
                
                while job_key.IsPaused() or job_key.IsCancelled():
                    
                    time.sleep( 0.1 )
                    
                    if job_key.IsCancelled():
                        
                        job_key.DeleteVariable( 'popup_gauge_1' )
                        job_key.SetVariable( 'popup_text_1', 'cancelled' )
                        
                        HydrusData.Print( job_key.ToString() )
                        
                        job_key.Delete( 5 )
                        
                        return
                        
                    
                
                try:
                    
                    if service_type in HC.REPOSITORIES:
                        
                        if isinstance( result, ClientMedia.MediaResult ):
                            
                            media_result = result
                            
                            client_files_manager = self._controller.client_files_manager
                            
                            hash = media_result.GetHash()
                            mime = media_result.GetMime()
                            
                            path = client_files_manager.GetFilePath( hash, mime )
                            
                            with open( path, 'rb' ) as f: file = f.read()
                            
                            service.Request( HC.POST, 'file', { 'file' : file } )
                            
                            file_info_manager = media_result.GetFileInfoManager()
                            
                            timestamp = HydrusData.GetNow()
                            
                            content_update_row = ( file_info_manager, timestamp )
                            
                            content_updates = [ HydrusData.ContentUpdate( HC.CONTENT_TYPE_FILES, HC.CONTENT_UPDATE_ADD, content_update_row ) ]
                            
                        else:
                            
                            client_to_server_update = result
                            
                            service.Request( HC.POST, 'update', { 'client_to_server_update' : client_to_server_update } )
                            
                            content_updates = client_to_server_update.GetClientsideContentUpdates()
                            
                        
                        self._controller.WriteSynchronous( 'content_updates', { service_key : content_updates } )
                        
                    elif service_type == HC.IPFS:
                        
                        if isinstance( result, ClientMedia.MediaResult ):
                            
                            media_result = result
                            
                            hash = media_result.GetHash()
                            mime = media_result.GetMime()
                            
                            service.PinFile( hash, mime )
                            
                        else:
                            
                            ( hash, multihash ) = result
                            
                            service.UnpinFile( hash, multihash )
                            
                        
                    
                except HydrusExceptions.ServerBusyException:
                    
                    job_key.SetVariable( 'popup_text_1', service.GetName() + ' was busy. please try again in a few minutes' )
                    
                    job_key.Cancel()
                    
                    return
                    
                
                self._controller.pub( 'notify_new_pending' )
                
                time.sleep( 0.1 )
                
                self._controller.WaitUntilViewFree()
                
                result = self._controller.Read( 'pending', service_key )
                
            
        except Exception as e:
            
            job_key.SetVariable( 'popup_text_1', service.GetName() + ' error' )
            
            job_key.Cancel()
            
            raise
            
        
        job_key.DeleteVariable( 'popup_gauge_1' )
        job_key.SetVariable( 'popup_text_1', u'upload done!' )
        
        HydrusData.Print( job_key.ToString() )
        
        job_key.Finish()
        
        job_key.Delete( 5 )
        
    
    def AddModalMessage( self, job_key ):
        
        if job_key.IsCancelled() or job_key.IsDeleted():
            
            return
            
        
        if job_key.IsDone():
            
            self._controller.pub( 'message', job_key )
            
            return
            
        
        if self.IsIconized():
            
            self._controller.CallLaterWXSafe( self, 10, self.AddModalMessage, job_key )
            
        else:
            
            title = job_key.GetIfHasVariable( 'popup_title' )
            
            if title is None:
                
                title = 'important job'
                
            
            with ClientGUITopLevelWindows.DialogNullipotentVetoable( self, title ) as dlg:
                
                panel = ClientGUIPopupMessages.PopupMessageDialogPanel( dlg, job_key )
                
                dlg.SetPanel( panel )
                
                r = dlg.ShowModal()
                
            
        
    
    def CurrentlyBusy( self ):
        
        return False
        
    
    def DeleteAllClosedPages( self ):
        
        with self._lock:
            
            deletee_pages = [ page for ( time_closed, page ) in self._closed_pages ]
            
            self._closed_pages = []
            self._closed_page_keys = set()
            
        
        if len( deletee_pages ) > 0:
            
            self._DestroyPages( deletee_pages )
            
            self._focus_holder.SetFocus()
            
            self._controller.pub( 'notify_new_undo' )
            
        
    
    def DeleteOldClosedPages( self ):
        
        new_closed_pages = []
        
        now = HydrusData.GetNow()
        
        timeout = 60 * 60
        
        with self._lock:
            
            deletee_pages = []
            
            old_closed_pages = self._closed_pages
            
            self._closed_pages = []
            self._closed_page_keys = set()
            
            for ( time_closed, page ) in old_closed_pages:
                
                if time_closed + timeout < now:
                    
                    deletee_pages.append( page )
                    
                else:
                    
                    self._closed_pages.append( ( time_closed, page ) )
                    self._closed_page_keys.add( page.GetPageKey() )
                    
                
            
            if len( old_closed_pages ) != len( self._closed_pages ):
                
                self._controller.pub( 'notify_new_undo' )
                
            
        
        self._DestroyPages( deletee_pages )
        
    
    def EventCharHook( self, event ):
        
        if ClientGUIShortcuts.IShouldCatchCharHook( self ):
            
            shortcut = ClientData.ConvertKeyEventToShortcut( event )
            
            if shortcut is not None:
                
                shortcut_processed = self._ProcessShortcut( shortcut )
                
                if shortcut_processed:
                    
                    return
                    
                
            
        
        event.Skip()
        
    
    def EventClose( self, event ):
        
        if not event.CanVeto():
            
            HG.emergency_exit = True
            
        
        exit_allowed = self.Exit()
        
        if not exit_allowed:
            
            event.Veto()
            
        
    
    def EventFocus( self, event ):
        
        page = self._notebook.GetCurrentMediaPage()
        
        if page is not None:
            
            page.SetMediaFocus()
            
        
    
    def EventFrameNewPage( self, event ):
        
        if self._controller.MenuIsOpen():
            
            return
            
        
        screen_position = wx.GetMousePosition()
        
        self._notebook.EventNewPageFromScreenPosition( screen_position )
        
    
    def EventFrameNotebookMenu( self, event ):
        
        screen_position = wx.GetMousePosition()
        
        self._notebook.EventMenuFromScreenPosition( screen_position )
        
    
    def TIMEREventAnimationUpdate( self, event ):
        
        for window in list( self._animation_update_windows ):
            
            if not window:
                
                self._animation_update_windows.discard( window )
                
                continue
                
            
            try:
                
                if HG.ui_timer_profile_mode:
                    
                    summary = 'Profiling animation timer: ' + repr( window )
                    
                    HydrusData.Profile( summary, 'window.TIMERAnimationUpdate()', globals(), locals(), min_duration_ms = 3 )
                    
                else:
                    
                    window.TIMERAnimationUpdate()
                    
                
            except Exception as e:
                
                self._animation_update_windows.discard( window )
                
                HydrusData.ShowException( e )
                
            
        
        if len( self._animation_update_windows ) == 0:
            
            self._animation_update_timer.Stop()
            
        
    
    def TIMEREventBandwidth( self, event ):
        
        global_tracker = self._controller.network_engine.bandwidth_manager.GetTracker( ClientNetworking.GLOBAL_NETWORK_CONTEXT )
        
        boot_time = self._controller.GetBootTime()
        
        time_since_boot = max( 1, HydrusData.GetNow() - boot_time )
        
        usage_since_boot = global_tracker.GetUsage( HC.BANDWIDTH_TYPE_DATA, time_since_boot )
        
        bandwidth_status = HydrusData.ConvertIntToBytes( usage_since_boot )
        
        current_usage = global_tracker.GetUsage( HC.BANDWIDTH_TYPE_DATA, 1, for_user = True )
        
        if current_usage > 0:
            
            bandwidth_status += ' (' + HydrusData.ConvertIntToBytes( current_usage ) + '/s)'
            
        
        self._statusbar.SetStatusText( bandwidth_status, 1 )
        
    
    def TIMEREventPageUpdate( self, event ):
        
        page = self.GetCurrentPage()
        
        if page is not None:
            
            if HG.ui_timer_profile_mode:
                
                summary = 'Profiling page timer: ' + repr( page )
                
                HydrusData.Profile( summary, 'page.TIMERPageUpdate()', globals(), locals(), min_duration_ms = 3 )
                
            else:
                
                page.TIMERPageUpdate()
                
            
        
    
    def TIMEREventUIUpdate( self, event ):
        
        for window in list( self._ui_update_windows ):
            
            if not window:
                
                self._ui_update_windows.discard( window )
                
                continue
                
            
            try:
                
                if HG.ui_timer_profile_mode:
                    
                    summary = 'Profiling ui update timer: ' + repr( window )
                    
                    HydrusData.Profile( summary, 'window.TIMERUIUpdate()', globals(), locals(), min_duration_ms = 3 )
                    
                else:
                    
                    window.TIMERUIUpdate()
                    
                
            except Exception as e:
                
                self._ui_update_windows.discard( window )
                
                HydrusData.ShowException( e )
                
            
        
        if len( self._ui_update_windows ) == 0:
            
            self._ui_update_timer.Stop()
            
        
    
    def Exit( self, restart = False ):
        
        # the return value here is 'exit allowed'
        
        if not HG.emergency_exit:
            
            if HC.options[ 'confirm_client_exit' ]:
                
                if restart:
                    
                    text = 'Are you sure you want to restart the client? (Will auto-yes in 15 seconds)'
                    
                else:
                    
                    text = 'Are you sure you want to exit the client? (Will auto-yes in 15 seconds)'
                    
                
                with ClientGUIDialogs.DialogYesNo( self, text ) as dlg:
                    
                    job = self._controller.CallLaterWXSafe( dlg, 15, dlg.EndModal, wx.ID_YES )
                    
                    try:
                        
                        if dlg.ShowModal() == wx.ID_NO:
                            
                            return False
                            
                        
                    finally:
                        
                        job.Cancel()
                        
                    
                
            
            try:
                
                self._notebook.TestAbleToClose()
                
            except HydrusExceptions.PermissionException:
                
                return False
                
            
        
        if restart:
            
            HG.restart = True
            
        
        try:
            
            self._notebook.SaveGUISession( 'last session' )
            
            self._DestroyTimers()
            
            self.DeleteAllClosedPages() # wx crashes if any are left in here, wew
            
            self._message_manager.CleanBeforeDestroy()
            
            self._message_manager.Hide()
            
            self._notebook.CleanBeforeDestroy()
            
            page = self._notebook.GetCurrentMediaPage()
            
            if page is not None:
                
                ( HC.options[ 'hpos' ], HC.options[ 'vpos' ] ) = page.GetSashPositions()
                
            
            ClientGUITopLevelWindows.SaveTLWSizeAndPosition( self, self._frame_key )
            
            self._controller.WriteSynchronous( 'save_options', HC.options )
            
            self._controller.WriteSynchronous( 'serialisable', self._new_options )
            
        except Exception as e:
            
            HydrusData.PrintException( e )
            
        
        for tlp in wx.GetTopLevelWindows():
            
            tlp.Hide()
            
        
        if HG.emergency_exit:
            
            self.Destroy()
            
            self._controller.Exit()
            
        else:
            
            self._controller.CallLaterWXSafe( self, 2, self.Destroy )
            
            self._controller.CreateSplash()
            
            wx.CallAfter( self._controller.Exit )
            
        
        self.Destroy()
        
        return True
        
    
    def FlipDarkmode( self ):
        
        current_colourset = self._new_options.GetString( 'current_colourset' )
        
        if current_colourset == 'darkmode':
            
            new_colourset = 'default'
            
        elif current_colourset == 'default':
            
            new_colourset = 'darkmode'
            
        
        self._new_options.SetString( 'current_colourset', new_colourset )
        
    
    def FlushOutPredicates( self, predicates ):
        
        good_predicates = []
        
        for predicate in predicates:
            
            predicate = predicate.GetCountlessCopy()
            
            ( predicate_type, value, inclusive ) = predicate.GetInfo()
            
            if value is None and predicate_type in [ HC.PREDICATE_TYPE_SYSTEM_NUM_TAGS, HC.PREDICATE_TYPE_SYSTEM_LIMIT, HC.PREDICATE_TYPE_SYSTEM_SIZE, HC.PREDICATE_TYPE_SYSTEM_DIMENSIONS, HC.PREDICATE_TYPE_SYSTEM_AGE, HC.PREDICATE_TYPE_SYSTEM_HASH, HC.PREDICATE_TYPE_SYSTEM_DURATION, HC.PREDICATE_TYPE_SYSTEM_NUM_WORDS, HC.PREDICATE_TYPE_SYSTEM_MIME, HC.PREDICATE_TYPE_SYSTEM_RATING, HC.PREDICATE_TYPE_SYSTEM_SIMILAR_TO, HC.PREDICATE_TYPE_SYSTEM_FILE_SERVICE, HC.PREDICATE_TYPE_SYSTEM_TAG_AS_NUMBER, HC.PREDICATE_TYPE_SYSTEM_DUPLICATE_RELATIONSHIPS ]:
                
                with ClientGUIDialogs.DialogInputFileSystemPredicates( self, predicate_type ) as dlg:
                    
                    if dlg.ShowModal() == wx.ID_OK:
                        
                        good_predicates.extend( dlg.GetPredicates() )
                        
                    else:
                        
                        continue
                        
                    
                
            elif predicate_type == HC.PREDICATE_TYPE_SYSTEM_UNTAGGED:
                
                good_predicates.append( ClientSearch.Predicate( HC.PREDICATE_TYPE_SYSTEM_NUM_TAGS, ( '=', 0 ) ) )
                
            else:
                
                good_predicates.append( predicate )
                
            
        
        return good_predicates
        
    
    def GetCurrentPage( self ):
        
        return self._notebook.GetCurrentMediaPage()
        
    
    def GetTotalPageCounts( self ):
        
        total_active_page_count = self._notebook.GetNumPages()
        
        total_closed_page_count = len( self._closed_pages )
        
        return ( total_active_page_count, total_closed_page_count )
        
    
    def IShouldRegularlyUpdate( self, window ):
        
        current_page = self.GetCurrentPage()
        
        if current_page is None:
            
            return False
            
        
        in_current_page = ClientGUICommon.IsWXAncestor( window, current_page )
        
        in_other_window = ClientGUICommon.GetTLP( window ) != self
        
        return in_current_page or in_other_window
        
    
    def ImportFiles( self, paths ):
        
        # can more easily do this when seeds are doing their own tags
        
        # get current media page
        # if it is an import page, ask user if they want to add it to the page or make a new one
        # if using existing, then load the panel without file import options
        # think about how to merge 'delete_after_success' or not--maybe this can be handled by seeds as well
        
        paths = [ HydrusData.ToUnicode( path ) for path in paths ]
        
        self._ImportFiles( paths )
        
    
    def ImportURL( self, url ):
        
        domain_manager = self._controller.network_engine.domain_manager
        
        ( url_type, match_name, can_parse ) = domain_manager.GetURLParseCapability( url )
        
        if url_type in ( HC.URL_TYPE_UNKNOWN, HC.URL_TYPE_FILE ):
            
            page = self._notebook.GetOrMakeURLImportPage()
            
            if page is not None:
                
                self._notebook.ShowPage( page )
                
                page_key = page.GetPageKey()
                
                HG.client_controller.pub( 'pend_raw_url', page_key, url )
                
            
        else:
            
            # url was recognised as a gallery, page, or watchable url
            
            if not can_parse:
                
                message = 'This URL was recognised as a "' + match_name + '" but this URL class does not yet have a parsing script linked to it!'
                message += os.linesep * 2
                message += 'Since this URL cannot be parsed, a downloader cannot be created for it! Please check your url class links under the \'networking\' menu.'
                
                wx.MessageBox( message )
                
                return
                
            
            # watchable url (thread url) -> open new watcher, set it
                # at some point, append it to existing multiple-thread-supporting-page
            # gallery url -> open gallery page for the respective parser for import options, but no query input stuff, queue up gallery page to be parsed for page urls
            # page url -> open gallery page for the respective parser for import options, but no query input stuff (maybe no gallery stuff, but this is prob overkill), queue up file page to be parsed for tags and file
            
            if url_type == HC.URL_TYPE_WATCHABLE:
                
                self._notebook.NewPageImportThreadWatcher( url, on_deepest_notebook = True )
                
                return
                
            
        
    
    def IsCurrentPage( self, page_key ):
        
        result = self._notebook.GetCurrentMediaPage()
        
        if result is None:
            
            return False
            
        else:
            
            return page_key == result.GetPageKey()
            
        
    
    def NewPageImportHDD( self, paths, file_import_options, paths_to_tags, delete_after_success ):
        
        management_controller = ClientGUIManagement.CreateManagementControllerImportHDD( paths, file_import_options, paths_to_tags, delete_after_success )
        
        self._notebook.NewPage( management_controller, on_deepest_notebook = True )
        
    
    def NewPageQuery( self, service_key, initial_hashes = None, initial_predicates = None, page_name = None, do_sort = False ):
        
        if initial_hashes is None:
            
            initial_hashes = []
            
        
        if initial_predicates is None:
            
            initial_predicates = []
            
        
        self._notebook.NewPageQuery( service_key, initial_hashes = initial_hashes, initial_predicates = initial_predicates, page_name = page_name, on_deepest_notebook = True, do_sort = do_sort )
        
    
    def NotifyClosedPage( self, page ):
        
        close_time = HydrusData.GetNow()
        
        with self._lock:
            
            self._closed_pages.append( ( close_time, page ) )
            self._closed_page_keys.add( page.GetPageKey() )
            
        
        if self._notebook.GetNumPages() == 0:
            
            self._focus_holder.SetFocus()
            
        
        self._DirtyMenu( 'pages' )
        
        self._menu_updater.Update()
        
    
    def NotifyNewImportFolders( self ):
        
        self._DirtyMenu( 'file' )
        
        self._menu_updater.Update()
        
    
    def NotifyNewOptions( self ):
        
        self._DirtyMenu( 'services' )
        self._DirtyMenu( 'help' )
        
        self._menu_updater.Update()
        
    
    def NotifyNewPages( self ):
        
        self._DirtyMenu( 'pages' )
        
        self._menu_updater.Update()
        
    
    def NotifyNewPending( self ):
        
        self._DirtyMenu( 'pending' )
        
        self._menu_updater.Update()
        
    
    def NotifyNewPermissions( self ):
        
        self._DirtyMenu( 'pages' )
        self._DirtyMenu( 'services' )
        self._DirtyMenu( 'network' )
        
        self._menu_updater.Update()
        
    
    def NotifyNewServices( self ):
        
        self._DirtyMenu( 'pages' )
        self._DirtyMenu( 'services' )
        self._DirtyMenu( 'network' )
        
        self._menu_updater.Update()
        
    
    def NotifyNewSessions( self ):
        
        self._DirtyMenu( 'pages' )
        
        self._menu_updater.Update()
        
    
    def NotifyNewUndo( self ):
        
        self._DirtyMenu( 'undo' )
        
        self._menu_updater.Update()
        
    
    def PageCompletelyDestroyed( self, page_key ):
        
        with self._lock:
            
            return page_key in self._deleted_page_keys
            
        
    
    def PageClosedButNotDestroyed( self, page_key ):
        
        with self._lock:
            
            return page_key in self._closed_page_keys
            
        
        return False
        
    
    def PresentImportedFilesToPage( self, hashes, page_name ):
        
        dest_page = self._notebook.PresentImportedFilesToPage( hashes, page_name )
        
    
    def RefreshMenu( self ):
        
        if not self:
            
            return
            
        
        db_going_to_hang_if_we_hit_it = HG.client_controller.DBCurrentlyDoingJob()
        
        if db_going_to_hang_if_we_hit_it:
            
            self._controller.CallLaterWXSafe( self, 0.5, self.RefreshMenu )
            
            return
            
        
        for name in self._dirty_menus:
            
            ( menu, label, show ) = self._GenerateMenuInfo( name )
            
            if HC.PLATFORM_OSX:
                
                menu.SetTitle( label ) # causes bugs in os x if this is not here
                
            
            ( old_menu, old_label, old_show ) = self._menus[ name ]
            
            if old_show:
                
                old_menu_index = self._menubar.FindMenu( old_label )
                
                if show:
                    
                    self._menubar.Replace( old_menu_index, menu, label )
                    
                else:
                    
                    self._menubar.Remove( old_menu_index )
                    
                
            else:
                
                if show:
                    
                    insert_index = 0
                    
                    for temp_name in MENU_ORDER:
                        
                        if temp_name == name: break
                        
                        ( temp_menu, temp_label, temp_show ) = self._menus[ temp_name ]
                        
                        if temp_show:
                            
                            insert_index += 1
                            
                        
                    
                    self._menubar.Insert( insert_index, menu, label )
                    
                
            
            self._menus[ name ] = ( menu, label, show )
            
            ClientGUIMenus.DestroyMenu( old_menu )
            
        
        self._dirty_menus = set()
        
    
    def RefreshStatusBar( self ):
        
        self._RefreshStatusBar()
        
    
    def RegisterAnimationUpdateWindow( self, window ):
        
        self._animation_update_windows.add( window )
        
        if self._animation_update_timer is not None and not self._animation_update_timer.IsRunning():
            
            self._animation_update_timer.Start( 5, wx.TIMER_CONTINUOUS )
            
        
    
    def RegisterUIUpdateWindow( self, window ):
        
        self._ui_update_windows.add( window )
        
        if self._ui_update_timer is not None and not self._ui_update_timer.IsRunning():
            
            self._ui_update_timer.Start( 100, wx.TIMER_CONTINUOUS )
            
        
    
    def RenamePage( self, page_key, name ):
        
        self._notebook.RenamePage( page_key, name )
        
    
    def SaveLastSession( self ):
        
        if HC.options[ 'default_gui_session' ] == 'last session':
            
            self._notebook.SaveGUISession( 'last session' )
            
        
        last_session_save_period_minutes = self._controller.new_options.GetInteger( 'last_session_save_period_minutes' )
        
        self._controller.CallLaterWXSafe( self, last_session_save_period_minutes * 60, self.SaveLastSession )
        
    
    def SetMediaFocus( self ):
        
        self._SetMediaFocus()
        
    
    def SetStatusBarDirty( self ):
        
        if not self:
            
            return
            
        
        self._statusbar_thread_updater.Update()
        
    
    def SyncToTagArchive( self, hta_path, tag_service_key, file_service_key, adding, namespaces, hashes = None ):
        
        self._controller.CallToThread( self._THREADSyncToTagArchive, hta_path, tag_service_key, file_service_key, adding, namespaces, hashes )
        
    
    def UnregisterAnimationUpdateWindow( self, window ):
        
        self._animation_update_windows.discard( window )
        
    
    def UnregisterUIUpdateWindow( self, window ):
        
        self._ui_update_windows.discard( window )
        
    
# We have this to be an off-wx-thread-happy container for this info, as the framesplash has to deal with messages in the fuzzy time of shutdown
# all of a sudden, pubsubs are processed in non wx-thread time, so this handles that safely and lets the gui know if the wx controller is still running
class FrameSplashStatus( object ):
    
    def __init__( self, controller, ui ):
        
        self._controller = controller
        self._ui = ui
        
        self._lock = threading.Lock()
        
        self._title_text = ''
        self._status_text = ''
        self._status_subtext = ''
        
        self._controller.sub( self, 'SetTitleText', 'splash_set_title_text' )
        self._controller.sub( self, 'SetText', 'splash_set_status_text' )
        self._controller.sub( self, 'SetSubtext', 'splash_set_status_subtext' )
        
    
    def _NotifyUI( self ):
        
        def wx_code():
            
            if not self._ui:
                
                return
                
            
            self._ui.SetDirty()
            
        
        wx.CallAfter( wx_code )
        
    
    def GetTexts( self ):
        
        with self._lock:
            
            return ( self._title_text, self._status_text, self._status_subtext )
            
        
    
    def SetText( self, text, print_to_log = True ):
        
        if print_to_log:
            
            HydrusData.Print( text )
            
        
        with self._lock:
            
            self._status_text = text
            self._status_subtext = ''
            
        
        self._NotifyUI()
        
    
    def SetSubtext( self, text ):
        
        with self._lock:
            
            self._status_subtext = text
            
        
        self._NotifyUI()
        
    
    def SetTitleText( self, text, print_to_log = True ):
        
        if print_to_log:
            
            HydrusData.Print( text )
            
        
        with self._lock:
            
            self._title_text = text
            self._status_text = ''
            self._status_subtext = ''
            
        
        self._NotifyUI()
        
    
class FrameSplash( wx.Frame ):
    
    WIDTH = 480
    HEIGHT = 280
    
    def __init__( self, controller ):
        
        self._controller = controller
        
        style = wx.FRAME_NO_TASKBAR
        
        wx.Frame.__init__( self, None, style = style, title = 'hydrus client' )
        
        self._dirty = True
        
        self._my_status = FrameSplashStatus( self._controller, self )
        
        self._bmp = wx.Bitmap( self.WIDTH, self.HEIGHT, 24 )
        
        self.SetSize( ( self.WIDTH, self.HEIGHT ) )
        
        self.Center()
        
        self._drag_init_click_coordinates = None
        self._drag_init_position = None
        self._initial_position = self.GetPosition()
        
        # this is 124 x 166
        self._hydrus = wx.Bitmap( os.path.join( HC.STATIC_DIR, 'hydrus_splash.png' ) )
        
        self.Bind( wx.EVT_PAINT, self.EventPaint )
        self.Bind( wx.EVT_MOTION, self.EventDrag )
        self.Bind( wx.EVT_LEFT_DOWN, self.EventDragBegin )
        self.Bind( wx.EVT_LEFT_UP, self.EventDragEnd )
        self.Bind( wx.EVT_ERASE_BACKGROUND, self.EventEraseBackground )
        
        self.Show( True )
        
        self.Raise()
        
    
    def _Redraw( self, dc ):
        
        ( title_text, status_text, status_subtext ) = self._my_status.GetTexts()
        
        dc.SetBackground( wx.Brush( wx.SystemSettings.GetColour( wx.SYS_COLOUR_WINDOW ) ) )
        
        dc.Clear()
        
        #
        
        x = ( self.WIDTH - 124 ) / 2
        y = 15
        
        dc.DrawBitmap( self._hydrus, x, y )
        
        dc.SetFont( wx.SystemSettings.GetFont( wx.SYS_DEFAULT_GUI_FONT ) )
        
        y += 166 + 15
        
        #
        
        ( width, height ) = dc.GetTextExtent( title_text )
        
        text_gap = ( self.HEIGHT - y - height * 3 ) / 4
        
        x = ( self.WIDTH - width ) / 2
        y += text_gap
        
        dc.DrawText( title_text, x, y )
        
        #
        
        y += height + text_gap
        
        ( width, height ) = dc.GetTextExtent( status_text )
        
        x = ( self.WIDTH - width ) / 2
        
        dc.DrawText( status_text, x, y )
        
        #
        
        y += height + text_gap
        
        ( width, height ) = dc.GetTextExtent( status_subtext )
        
        x = ( self.WIDTH - width ) / 2
        
        dc.DrawText( status_subtext, x, y )
        
    
    def EventDrag( self, event ):
        
        if event.Dragging() and self._drag_init_click_coordinates is not None:
            
            ( init_x, init_y ) = self._drag_init_click_coordinates
            
            ( x, y ) = wx.GetMousePosition()
            
            total_drag_delta = ( x - init_x, y - init_y )
            
            #
            
            ( init_x, init_y ) = self._drag_init_position
            
            ( total_delta_x, total_delta_y ) = total_drag_delta
            
            self.SetPosition( ( init_x + total_delta_x, init_y + total_delta_y ) )
            
        
    
    def EventDragBegin( self, event ):
        
        self._drag_init_click_coordinates = wx.GetMousePosition()
        self._drag_init_position = self.GetPosition()
        
        event.Skip()
        
    
    def EventDragEnd( self, event ):
        
        self._drag_init_click_coordinates = None
        
        event.Skip()
        
    
    def EventEraseBackground( self, event ):
        
        pass
        
    
    def EventPaint( self, event ):
        
        dc = wx.BufferedPaintDC( self, self._bmp )
        
        if self._dirty:
            
            self._Redraw( dc )
            
        
    
    def SetDirty( self ):
        
        if not self:
            
            return
            
        
        self._dirty = True
        
        self.Refresh()
        
    
