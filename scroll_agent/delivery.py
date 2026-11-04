"""Authorized short-message transport shared by rounds and task reports."""
import json
import time
import uuid

from video_reader.common import ReaderError
from video_reader.platform import PlatformError

ENDPOINT='https://api.vc.bilibili.com/web_im/v1/web_im/send_msg'


def send_message(platform,memory,recipient,text,keys,*,on_reserved=None):
    if recipient is None or not platform.sender or not platform.csrf:
        raise ReaderError('Private delivery needs a recipient and the component login/CSRF token')
    if len(text)>450: raise ReaderError('Private message exceeds the local short-message limit')
    if not memory.reserve_delivery(recipient,keys):
        return {'status':'duplicate_or_uncertain_not_resent'}
    if on_reserved: on_reserved()
    form={'msg[sender_uid]':platform.sender,'msg[receiver_id]':str(recipient),
        'msg[receiver_type]':1,'msg[msg_type]':1,'msg[msg_status]':0,
        'msg[content]':json.dumps({'content':text},ensure_ascii=False),
        'msg[timestamp]':int(time.time()),'msg[new_face_version]':0,
        'msg[dev_id]':str(uuid.uuid4()).upper(),'csrf':platform.csrf,'csrf_token':platform.csrf}
    try:
        response=platform.request(ENDPOINT,form=form)
        accepted=isinstance(response,dict) and response.get('code')==0 and (response.get('data') or {}).get('msg_key')
        status='accepted_not_receipt_verified' if accepted else 'uncertain'
        memory.delivery_result(recipient,keys,status)
        return {'status':status,'receipt_verified':False,
                'message_key':str(response['data']['msg_key']) if accepted else None}
    except (ReaderError,OSError) as error:
        status='rejected' if isinstance(error,PlatformError) and error.code.startswith('platform_code:') else 'uncertain'
        memory.delivery_result(recipient,keys,status)
        return {'status':status,'error':str(error),'automatic_retry':False}
