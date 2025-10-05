import os, gc
from .httpclient import HttpClient

class OTAUpdater:
    """
    A class to update your MicroController with the latest version from a GitHub tagged release,
    optimized for low power usage.
    """

    def __init__(self, github_repo, github_src_dir='', module='', main_dir='', new_version_dir='next', secrets_file=None, headers={}):
        self.http_client = HttpClient(headers=headers)
        self.github_repo = github_repo.rstrip('/').replace('https://github.com/', '')
        self.github_src_dir = '' if len(github_src_dir) < 1 else github_src_dir.rstrip('/') + '/'
        self.module = module.rstrip('/')
        self.main_dir = main_dir
        self.new_version_dir = new_version_dir
        self.secrets_file = secrets_file

    def __del__(self):
        self.http_client = None

    def check_for_update_to_install_during_next_reboot(self) -> bool:
        """Function which will check the GitHub repo if there is a newer version available.
        
        This method expects an active internet connection and will compare the current 
        version with the latest version available on GitHub.
        If a newer version is available, the file 'next/.version' will be created 
        and you need to call machine.reset(). A reset is needed as the installation process 
        takes up a lot of memory (mostly due to the http stack)

        Returns
        -------
            bool: true if a new version is available, false otherwise
        """
        
        # Check if SSL is available (required for GitHub API)
        try:
            import ussl
        except ImportError:
            print('SSL not available, OTA updates disabled')
            return False

        try:
            (current_version, latest_version) = self._check_for_new_version()
            if self._compare_versions(current_version, latest_version):
                print('New version available, will download and install on next reboot')
                self._create_new_version_file(latest_version)
                return True
        except Exception as e:
            print('OTA check failed:', e)
            return False

        return False

    def install_update_if_available_after_boot(self, ssid, password) -> bool:
        """This method will install the latest version if out-of-date after boot.
        
        This method, which should be called first thing after booting, will check if the 
        next/.version' file exists. 

        - If yes, it initializes the WIFI connection, downloads the latest version and installs it
        - If no, the WIFI connection is not initialized as no new known version is available
        """
        
        # Check if SSL is available (required for GitHub API)
        try:
            import ussl
        except ImportError:
            print('SSL not available, OTA updates disabled')
            return False

        if self.new_version_dir in os.listdir(self.module):
            if '.version' in os.listdir(self.modulepath(self.new_version_dir)):
                latest_version = self.get_version(self.modulepath(self.new_version_dir), '.version')
                print('New update found: ', latest_version)
                OTAUpdater._using_network(ssid, password)
                self.install_update_if_available()
                return True
            
        print('No new updates found...')
        return False

    def install_update_if_available(self) -> bool:
        """This method will immediately install the latest version if out-of-date.
        
        This method expects an active internet connection and allows you to decide yourself
        if you want to install the latest version. It is necessary to run it directly after boot 
        (for memory reasons) and you need to restart the microcontroller if a new version is found.

        Returns
        -------
            bool: true if a new version is available, false otherwise
        """
        
        # Check if SSL is available (required for GitHub API)
        try:
            import ussl
        except ImportError:
            print('SSL not available, OTA updates disabled')
            return False

        try:
            (current_version, latest_version) = self._check_for_new_version()
            if self._compare_versions(current_version, latest_version):
                print('Updating to version {}...'.format(latest_version))
                self._create_new_version_file(latest_version)
                self._download_new_version(latest_version)
                self._copy_secrets_file()
                self._delete_old_version()
                self._install_new_version()
                return True
        except Exception as e:
            print('OTA update failed:', e)
            return False
        
        return False


    @staticmethod
    def _using_network(ssid, password):
        import network
        sta_if = network.WLAN(network.STA_IF)
        if not sta_if.isconnected():
            print('connecting to network...')
            sta_if.active(True)
            sta_if.connect(ssid, password)
            while not sta_if.isconnected():
                pass
        print('network config:', sta_if.ifconfig())

    def _check_for_new_version(self):
        current_version = self.get_version(self.modulepath(self.main_dir))
        latest_version = self.get_latest_version()

        print('Checking version... ')
        print('\tCurrent version: ', current_version)
        print('\tLatest version: ', latest_version)
        
        # Debug version comparison
        is_newer = self._compare_versions(current_version, latest_version)
        print('\tIs newer version available: ', is_newer)
        
        return (current_version, latest_version)
    
    def _compare_versions(self, current, latest):
        """
        เปรียบเทียบเวอร์ชั่น semantic version (v1.2.3)
        Returns True ถ้า latest > current
        """
        def parse_version(version):
            # ลบ 'v' ข้างหน้าถ้ามี
            version = version.lstrip('v')
            try:
                parts = version.split('.')
                return [int(p) for p in parts]
            except:
                # fallback ถ้า parse ไม่ได้
                return [0, 0, 0]
        
        current_parts = parse_version(current)
        latest_parts = parse_version(latest)
        
        # เพิ่ม 0 ให้ครบ 3 ตัว
        while len(current_parts) < 3:
            current_parts.append(0)
        while len(latest_parts) < 3:
            latest_parts.append(0)
        
        # เปรียบเทียบแต่ละส่วน
        for i in range(3):
            if latest_parts[i] > current_parts[i]:
                return True
            elif latest_parts[i] < current_parts[i]:
                return False
        
        return False  # เวอร์ชั่นเหมือนกัน

    def _create_new_version_file(self, latest_version):
        self.mkdir(self.modulepath(self.new_version_dir))
        with open(self.modulepath(self.new_version_dir + '/.version'), 'w') as versionfile:
            versionfile.write(latest_version)
            versionfile.close()

    def get_version(self, directory, version_file_name='.version'):
        try:
            if version_file_name in os.listdir(directory):
                with open(directory + '/' + version_file_name) as f:
                    version = f.read()
                    return version.strip()
        except OSError:
            # Directory or file doesn't exist
            pass
        return '0.0'

    def get_latest_version(self):
        print('Fetching latest version from GitHub...')
        try:
            latest_release = self.http_client.get('https://api.github.com/repos/{}/releases/latest'.format(self.github_repo))
            response_data = latest_release.json()
            version = response_data['tag_name']
            latest_release.close()
            print('Successfully fetched latest version: ', version)
            return version
        except Exception as e:
            print('Error fetching latest version: ', e)
            raise

    def _download_new_version(self, version):
        print('Downloading version {}'.format(version))
        self._download_all_files(version)
        print('Version {} downloaded to {}'.format(version, self.modulepath(self.new_version_dir)))

    def _download_all_files(self, version, sub_dir=''):
        url = 'https://api.github.com/repos/{}/contents{}{}{}?ref=refs/tags/{}'.format(self.github_repo, self.github_src_dir, self.main_dir, sub_dir, version)
        gc.collect() 
        file_list = self.http_client.get(url)
        for file in file_list.json():
            path = self.modulepath(self.new_version_dir + '/' + file['path'].replace(self.main_dir + '/', '').replace(self.github_src_dir, ''))
            if file['type'] == 'file':
                gitPath = file['path']
                print('\tDownloading: ', gitPath, 'to', path)
                self._download_file(version, gitPath, path)
            elif file['type'] == 'dir':
                print('Creating dir', path)
                self.mkdir(path)
                self._download_all_files(version, sub_dir + '/' + file['name'])
            gc.collect()

        file_list.close()

    def _download_file(self, version, gitPath, path):
        self.http_client.get('https://raw.githubusercontent.com/{}/{}/{}'.format(self.github_repo, version, gitPath), saveToFile=path)

    def _copy_secrets_file(self):
        if self.secrets_file:
            fromPath = self.modulepath(self.main_dir + '/' + self.secrets_file)
            toPath = self.modulepath(self.new_version_dir + '/' + self.secrets_file)
            print('Copying secrets file from {} to {}'.format(fromPath, toPath))
            self._copy_file(fromPath, toPath)
            print('Copied secrets file from {} to {}'.format(fromPath, toPath))

    def _delete_old_version(self):
        print('Deleting old version at {} ...'.format(self.modulepath(self.main_dir)))
        self._rmtree(self.modulepath(self.main_dir))
        print('Deleted old version at {} ...'.format(self.modulepath(self.main_dir)))

    def _install_new_version(self):
        print('Installing new version at {} ...'.format(self.modulepath(self.main_dir)))
        if self._os_supports_rename():
            os.rename(self.modulepath(self.new_version_dir), self.modulepath(self.main_dir))
        else:
            self._copy_directory(self.modulepath(self.new_version_dir), self.modulepath(self.main_dir))
            self._rmtree(self.modulepath(self.new_version_dir))
        print('Update installed, please reboot now')
        
        # ส่ง MQTT notification หลัง OTA เสร็จ
        self._notify_ota_complete()
    
    def _notify_ota_complete(self):
        """ส่ง MQTT notification หลัง OTA เสร็จ"""
        try:
            # อ่านเวอร์ชั่นใหม่ที่เพิ่งติดตั้ง
            new_version = self.get_version(self.modulepath(self.main_dir))
            
            # ถ้ามี WiFi และ MQTT ให้ส่งข้อความ
            try:
                import network
                sta = network.WLAN(network.STA_IF)
                if sta.isconnected():
                    from mqtt import MQTTManager
                    mqtt = MQTTManager()
                    if mqtt.connect():
                        mqtt.publish_version(new_version, source="ota_update")
                        print(f"[OTA] Notified MQTT: version {new_version}")
            except Exception as e:
                print(f"[OTA] MQTT notification failed: {e}")
        except Exception as e:
            print(f"[OTA] Post-install notification error: {e}")

    def _rmtree(self, directory):
        for entry in os.ilistdir(directory):
            is_dir = entry[1] == 0x4000
            if is_dir:
                self._rmtree(directory + '/' + entry[0])
            else:
                os.remove(directory + '/' + entry[0])
        os.rmdir(directory)

    def _os_supports_rename(self) -> bool:
        self._mk_dirs('otaUpdater/osRenameTest')
        os.rename('otaUpdater', 'otaUpdated')
        result = len(os.listdir('otaUpdated')) > 0
        self._rmtree('otaUpdated')
        return result

    def _copy_directory(self, fromPath, toPath):
        if not self._exists_dir(toPath):
            self._mk_dirs(toPath)

        for entry in os.ilistdir(fromPath):
            is_dir = entry[1] == 0x4000
            if is_dir:
                self._copy_directory(fromPath + '/' + entry[0], toPath + '/' + entry[0])
            else:
                self._copy_file(fromPath + '/' + entry[0], toPath + '/' + entry[0])

    def _copy_file(self, fromPath, toPath):
        with open(fromPath) as fromFile:
            with open(toPath, 'w') as toFile:
                CHUNK_SIZE = 512 # bytes
                data = fromFile.read(CHUNK_SIZE)
                while data:
                    toFile.write(data)
                    data = fromFile.read(CHUNK_SIZE)
            toFile.close()
        fromFile.close()

    def _exists_dir(self, path) -> bool:
        try:
            os.listdir(path)
            return True
        except:
            return False

    def _mk_dirs(self, path:str):
        paths = path.split('/')

        pathToCreate = ''
        for x in paths:
            self.mkdir(pathToCreate + x)
            pathToCreate = pathToCreate + x + '/'

    # different micropython versions act differently when directory already exists
    def mkdir(self, path:str):
        try:
            os.mkdir(path)
        except OSError as exc:
            if exc.args[0] == 17: 
                pass


    def modulepath(self, path):
        return self.module + '/' + path if self.module else path