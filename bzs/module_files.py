
import socket
import threading
import tornado
import re
import io
import base64
import binascii

import tornado.ioloop
import tornado.iostream
import tornado.web
import tornado.gen
import tornado.httputil
from tornado.concurrent import run_on_executor

from bzs import files
from bzs import const
from bzs import users
from bzs import preproc

# TODO: Remove this!
import os

def encode_str_to_hexed_b64(data):
    return binascii.b2a_hex(base64.b64encode(data.encode('utf-8'))).decode('utf-8')
def decode_hexed_b64_to_str(data):
    return base64.b64decode(binascii.unhexlify(data.encode('utf-8'))).decode('utf-8')

class FilesListHandler(tornado.web.RequestHandler):
    SUPPORTED_METHODS = ['GET', 'HEAD']

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        # Getting file template.
        file_temp = files.get_static_data('./static/files.html')

        # Retrieving list target.
        target_path = re.sub('/files(/list/)?', '', self.request.uri)
        try:
            target_path = decode_hexed_b64_to_str(target_path)
        except:
            target_path = '/'
        if not target_path:
            target_path = '/'

        # Getting parental directorial list
        files_hierarchy = target_path.split('/')
        files_hierarchy_list = list()
        while '' in files_hierarchy:
            files_hierarchy.remove('')
        files_hierarchy = [''] + files_hierarchy
        files_hierarchy_cwd = ''
        for i in range(0, len(files_hierarchy)):
            files_hierarchy[i] += '/'
            files_hierarchy_cwd += files_hierarchy[i]
            files_hierarchy_list.append(dict(
                folder_name=files_hierarchy[i],
                href_path='/files/list/%s' % encode_str_to_hexed_b64(files_hierarchy_cwd),
                disabled=(i == len(files_hierarchy) - 1)))
            continue

        # Getting current directory content
        files_attrib_list = list()
        try: # In case of a permission error.
            for file_name in os.listdir(target_path):
                actual_path = target_path + file_name
                attrib = dict()
                attrib['file-name'] = file_name
                attrib['allow-edit'] = True
                attrib['file-size'] = '2.56 MB'
                attrib['owner'] = 'non-admin'
                attrib['date-uploaded'] = '08/08/2016 00:00:00'
                # Detecting whether is a folder
                if os.path.isdir(actual_path):
                    attrib['mime-type'] = 'directory/folder'
                else:
                    attrib['mime-type'] = files.guess_mime_type(file_name)
                # And access links should differ between folders and files
                if attrib['mime-type'] == 'directory/folder':
                    attrib['target-link'] = '/files/list/%s' % encode_str_to_hexed_b64(actual_path + '/')
                else:
                    attrib['target-link'] = '/files/download/%s/%s' % (encode_str_to_hexed_b64(actual_path), file_name)
                files_attrib_list.append(attrib)
        except Exception:
            pass

        # File actually exists, sending data
        working_user = users.get_user_by_cookie(
            self.get_cookie('user_active_login', default=''))
        file_temp = preproc.preprocess_webpage(file_temp, working_user,
            files_attrib_list=files_attrib_list,
            files_hierarchy_list=files_hierarchy_list)

        self.set_status(200, "OK")
        self.add_header('Cache-Control', 'max-age=0')
        self.add_header('Connection', 'close')
        self.add_header('Content-Type', 'text/html')
        self.add_header('Content-Length', str(len(file_temp)))
        self.write(file_temp)
        self.flush()
        self.finish()
        return self

    head=get
    pass


class FilesDownloadHandler(tornado.web.RequestHandler):
    SUPPORTED_METHODS = ['GET', 'HEAD']

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        # Something that I do not wish to write too many times..
        def invoke_404():
            self.set_status(404, "Not Found")
            self._headers = tornado.httputil.HTTPHeaders()
            self.add_header('Content-Length', '0')
            self.flush()
            return

        # Get file location (exactly...)
        file_path = re.sub(r'^/files/download/(.*?)/.*$', r'\1', self.request.uri)
        try:
            file_path = decode_hexed_b64_to_str(file_path)
        except Exception:
            target_path = ''
        if not file_path:
            invoke_404()
            return

        # File actually exists, sending data
        try:
            file_handle = open(file_path, 'rb')
        except Exception:
            invoke_404()
            return
        file_data = file_handle.read()
        file_handle.close()
        file_stream = io.BytesIO(file_data)

        self.set_status(200, "OK")
        self.add_header('Cache-Control', 'max-age=0')
        self.add_header('Connection', 'close')
        self.add_header('Content-Type', 'application/x-download')
        self.add_header('Content-Length', str(len(file_data)))

        # Asynchronous web request...
        file_block_size = 1024 * 1024 # 1.00 MiB / Chunk
        file_block = bytes()

        while file_stream.tell() < len(file_data):
            byte_pos = file_stream.tell()
            # Entry to the concurrency worker
            future = tornado.concurrent.Future()
            # Concurrent worker
            def retrieve_data_async():
                block = file_stream.read(file_block_size)
                future.set_result(block)
            # Injection and pending
            tornado.ioloop.IOLoop.instance().add_callback(retrieve_data_async)
            # Reset or read
            file_block = yield future
            self.write(file_block)
            file_block = None
            self.flush()
        file_block = None
        self.finish()

        # Release memory...
        file_stream = None
        file_data = None
        return self

    head=get
    pass