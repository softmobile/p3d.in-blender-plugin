bl_info = {
    'name': 'Upload glTF 2.0 to P3d.in',
    "version": (1, 0, 5),
    'blender': (2, 91, 0),
    'location': 'File > Export',
    'description': 'Upload as glTF 2.0 to P3d.in',
    'category': 'Import-Export',
}

import bpy
import os
import webbrowser
import json
import uuid
import time
import threading
from datetime import datetime, timedelta

import requests

from bpy_extras.io_utils import ExportHelper
from bpy.types import Operator, AddonPreferences
from bpy.props import (BoolProperty,
                       IntProperty,
                       StringProperty,
                       EnumProperty,
                       CollectionProperty
                       )


class P3dInPreferences(AddonPreferences):
    bl_idname = __name__
    authCode: StringProperty(default="")
    apiToken:StringProperty(default="")
    isBusy : BoolProperty(default=False)
    lastTokenTimestamp:StringProperty(default="")

class P3dInGetAuthCode(Operator):
    bl_idname = "getauthcode.p3din"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Get Auth Code"         # Display name in the interface.

    def execute(self, context):
        webbrowser.open_new('https://p3d.in/o/authorize/?client_id=kr4V9FRckMQdxlkB0eJo0EY0ka42gO2TO4XXnahZ&response_type=code&redirect_uri=https%3A%2F%2Fblender-addon.web.app')
        return {'FINISHED'}


class P3dInSync(Operator):
    """P3d.in Script"""      # Use this as a tooltip for menu items and buttons.
    bl_idname = "upload.p3din"        # Unique identifier for buttons and menu items to reference.
    bl_label = "Upload to P3d.in"         # Display name in the interface.
    bl_options = {'REGISTER', 'UNDO'}  # Enable undo for the operator.

    filename_ext = ''

    filter_glob: StringProperty(
            default='*.glb;*.gltf', 
            options={'HIDDEN'}
    )

    # List of operator properties, the attributes will be assigned
    # to the class instance from the operator setting before calling.
    batch_export_format: EnumProperty(
        name='Format',
        items=(('GLB', 'glTF Binary (.glb)',
                'Exports a single file, with all data packed in binary form. '
                'Most efficient and portable, but more difficult to edit later'),
               ('GLTF_EMBEDDED', 'glTF Embedded (.gltf)',
                'Exports a single file, with all data packed in JSON. '
                'Less efficient than binary, but easier to edit later'),
               ('GLTF_SEPARATE', 'glTF Separate (.gltf + .bin + textures)',
                'Exports multiple files, with separate JSON, binary and texture data. '
                'Easiest to edit later')),
        description=(
            'Output format and embedding options. Binary is most efficient, '
            'but JSON (embedded or separate) may be easier to edit later'
        ),
        default='GLB'
    )

    batch_export_copyright: StringProperty(
        name='Copyright',
        description='Legal rights and conditions for the model',
        default=''
    )

    batch_export_image_format: EnumProperty(
        name='Images',
        items=(('AUTO', 'Automatic',
                'Save PNGs as PNGs and JPEGs as JPEGs.\n'
                'If neither one, use PNG'),
                ('JPEG', 'JPEG Format (.jpg)',
                'Save images as JPEGs. (Images that need alpha are saved as PNGs though.)\n'
                'Be aware of a possible loss in quality'),
               ),
        description=(
            'Output format for images. PNG is lossless and generally preferred, but JPEG might be preferable for web '
            'applications due to the smaller file size'
        ),
        default='AUTO'
    )

    batch_export_levels: IntProperty(
        name='Collection Levels',
        description='Set the levels of collections',
        default=2
    )

    batch_export_materials: EnumProperty(
        name='Materials',
        items=(('EXPORT', 'Export',
        'Export all materials used by included objects'),
        ('PLACEHOLDER', 'Placeholder',
        'Do not export materials, but write multiple primitive groups per mesh, keeping material slot information'),
        ('NONE', 'No export',
        'Do not export materials, and combine mesh primitive groups, losing material slot information')),
        description='Export materials ',
        default='EXPORT'
    )

    batch_export_colors: BoolProperty(
        name='Export Vertex Colors',
        description='Export vertex colors with meshes',
        default=True
    )

    batch_export_cameras: BoolProperty(
        name='Export Cameras',
        description='Export cameras',
        default=False
    )

    batch_export_extras: BoolProperty(
        name='Export Custom Properties',
        description='Export custom properties as glTF extras',
        default=False
    )

    batch_export_apply: BoolProperty(
        name='Export Apply Modifiers',
        description='Apply modifiers (excluding Armatures) to mesh objects -'
                    'WARNING: prevents exporting shape keys',
        default=False
    )

    batch_export_yup: BoolProperty(
        name='+Y Up',
        description='Export using glTF convention, +Y up',
        default=True
    )

    authcode : bpy.props.StringProperty(
        name = "Authorization Code",
        description = "Authentication Code",
        default = ''
    )

    modelname : bpy.props.StringProperty(
        name = "Model Name",
        description = "Enter model name here.",
        default = ''
    )

    modeldescription : bpy.props.StringProperty(
        name = "Model Description",
        description = "Enter model description here.",
        default = ''
    )

    filetoupload : bpy.props.StringProperty(
        default = ''
    )

    def invoke(self, context, event):
        if(context.preferences.addons[__name__].preferences.isBusy):
            return self.execute(context)
        else:
            return context.window_manager.invoke_props_dialog(self, width = 400)

    def draw(self, context):
        layout = self.layout
        
        if not context.preferences.addons[__name__].preferences.authCode:
            col = layout.column()
            col.label(text="Paste authorization code here.")
            col.label(text="To get authorization code, click on Get Auth Code. Once P3d.in site is open in ")
            col.label(text="your browser, login with your credentials and it will take you to authorization ")
            col.label(text="page. Click Authorize and it will redirect to a new url as following")
            col.label(text="'https://blender-addon.web.app/?code=[Auth Code]'")
            col.label(text="Click [Click here to copy Authorization code] and paste it here.")
            col.label(text="")

            row = col.row()
            row.prop(self, "authcode")
            row.operator("getauthcode.p3din")
        
        col = layout.column()
        col.label(text="Enter details.")

        col.prop(self, "modelname")
        col.prop(self, "modeldescription")
        

    def fetchToken(self, context):
        token  = ""
        grant_type = "authorization_code"
        token_code  = "&code=" + context.preferences.addons[__name__].preferences.authCode

        try:
            try:
                oldtoken  = json.loads(context.preferences.addons[__name__].preferences.apiToken)
                last_check = context.preferences.addons[__name__].preferences.lastTokenTimestamp

                if datetime.now() < datetime.strptime(last_check, "%m/%d/%Y, %H:%M:%S"):
                    return oldtoken["access_token"]
                else:
                    grant_type = "refresh_token"
                    token_code = "&refresh_token=" + oldtoken["refresh_token"]
            except:
                pass

            headers = {'Content-Type': 'application/x-www-form-urlencoded'}

            payload='client_id=kr4V9FRckMQdxlkB0eJo0EY0ka42gO2TO4XXnahZ'+ token_code + '&grant_type='+ grant_type +'&redirect_uri=https%3A%2F%2Fblender-addon.web.app'
            
            response = requests.post('https://p3d.in/o/token/', data = payload, headers=headers)

            if not response.ok:
                context.preferences.addons[__name__].preferences.authCode = ""
                self.report({"ERROR"}, response.text)
            else:
                obj = json.loads(response.text)

                if obj["access_token"]:
                    context.preferences.addons[__name__].preferences.apiToken = response.text;
                    context.preferences.addons[__name__].preferences.lastTokenTimestamp = (datetime.now() + timedelta(seconds=obj["expires_in"])).strftime("%m/%d/%Y, %H:%M:%S")
                    token = obj["access_token"]
        except Exception as ex:
            if hasattr(ex, 'message'):
                self.report({"ERROR"}, ex.message)
            else:
                self.report({"ERROR"}, str(ex))

        return token 

    def execute(self, context):

        if(context.preferences.addons[__name__].preferences.isBusy):
            self.report({"WARNING"}, "Already processing!!")
            return {'FINISHED'}

        if self.authcode:
            context.preferences.addons[__name__].preferences.authCode = self.authcode
        #
        authCode = context.preferences.addons[__name__].preferences.authCode

        if not authCode:
            self.report({"ERROR"}, "Authentication code is required!!")
            return {'FINISHED'}

        if not self.modelname:
            self.report({"ERROR"}, "Model name is empty!!")
            return {'FINISHED'}

        if not self.modeldescription:
            self.report({"ERROR"}, "Model description is empty!!")
            return {'FINISHED'}

        self.report({"INFO"}, "Uploading..")
        
        curToken = self.fetchToken(context)

        if not curToken:
            self.report({"ERROR"}, "Failed to get auth token !!")
            return {'FINISHED'}

        fpath = os.path.join(bpy.app.tempdir, str(uuid.uuid4()) + '.glb')

        self.filetoupload  = fpath

        bpy.ops.export_scene.gltf(
                filepath = fpath,
                export_format = self.batch_export_format,
                export_copyright = self.batch_export_copyright,
                export_image_format = self.batch_export_image_format,
                export_materials = self.batch_export_materials,
                export_colors = self.batch_export_colors,
                export_cameras = self.batch_export_cameras,
                export_extras = self.batch_export_extras,
                export_yup = self.batch_export_yup,
                export_apply = self.batch_export_apply
            )

        """ [FIXME] On background thread its not possible to show progress or 
        even show status of upload at the end. so calling the code. inline for now. """
        #new_thread = threading.Thread() # create a new thread object.
        #new_thread.run = self.dobackground
        #new_thread.start() # the new thread is created and then is running.

        self.dobackground()

        return {'FINISHED'}

    def dobackground(self):
        try:
            bpy.context.preferences.addons[__name__].preferences.isBusy = True

            self.report({"INFO"}, "Posting to p3d.in....")

            print('posting to p3d.in')

            myobj = {"model_info" : "{\"name\":\""+ self.modelname +"\",\"description\":\""+ self.modeldescription +"\"}"}
            
            fileFp = open(self.filetoupload, 'rb')

            realpath = os.path.join(os.path.dirname(__file__), "thumb.png")
            thumbfile = open(realpath, 'rb')
            
            fileInfoDict = {
                "model": fileFp,
                "snapshot" : thumbfile
            }

            acttoken  = json.loads(bpy.context.preferences.addons[__name__].preferences.apiToken)

            response = requests.post('https://uploadsrv.p3d.in', files=fileInfoDict, 
            data = myobj,
            headers = {"Authorization": "Bearer " + acttoken["access_token"]}
            )

            if response.ok:
                self.report({"INFO"}, "Uploaded successfully.")
                print("Uploaded successfully.")
            elif response.status_code == 403 or response.status_code == 401:
                bpy.context.preferences.addons[__name__].preferences.apiToken = ''
                self.report({"ERROR"}, "Failed to authenticate. Retry !!")
            else:
                self.report({"ERROR"}, response.text)
        except Exception as ex:
            print("ERROR " + str(ex))
            self.report({"ERROR"}, str(ex))
            pass
        finally:
            bpy.context.preferences.addons[__name__].preferences.isBusy = False

def register():
    bpy.utils.register_class(P3dInSync)
    bpy.utils.register_class(P3dInGetAuthCode)
    bpy.types.TOPBAR_MT_file_export.append(menu_func)
    bpy.utils.register_class(P3dInPreferences)


def unregister():
    bpy.utils.unregister_class(P3dInPreferences)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func)
    bpy.utils.unregister_class(P3dInGetAuthCode)
    bpy.utils.unregister_class(P3dInSync)

def menu_func(self, context):
    self.layout.operator(P3dInSync.bl_idname)


# This allows you to run the script directly from Blender's Text editor
# to test the add-on without having to install it.
if __name__ == "__main__":
    register()