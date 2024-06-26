# -*- coding: utf-8 -*-#
# -------------------------------------------------------------------------------
# Name:         parsingMSG.py
# Description:  
# Author:       xaoyaoo
# Date:         2024/04/15
# -------------------------------------------------------------------------------
import os
import re

import pandas as pd

from .dbbase import DatabaseBase
from .utils import get_md5, name2typeid, typeid2name, timestamp2str, xml2dict, match_BytesExtra
import lz4.block
import blackboxprotobuf


class ParsingMSG(DatabaseBase):
    def __init__(self, db_path):
        super().__init__(db_path)

    def decompress_CompressContent(self, data):
        """
        解压缩Msg：CompressContent内容
        :param data: CompressContent内容 bytes
        :return:
        """
        if data is None or not isinstance(data, bytes):
            return None
        try:
            dst = lz4.block.decompress(data, uncompressed_size=len(data) << 8)
            dst = dst.replace(b'\x00', b'')  # 已经解码完成后，还含有0x00的部分，要删掉，要不后面ET识别的时候会报错
            uncompressed_data = dst.decode('utf-8', errors='ignore')
            return uncompressed_data
        except Exception as e:
            return data.decode('utf-8', errors='ignore')

    def get_BytesExtra(self, BytesExtra):
        if BytesExtra is None or not isinstance(BytesExtra, bytes):
            return None
        try:
            deserialize_data, message_type = blackboxprotobuf.decode_message(BytesExtra)
            return deserialize_data
        except Exception as e:
            return None

    def chat_count(self, wxid: str = ""):
        """
        获取聊天记录数量,根据wxid获取单个联系人的聊天记录数量，不传wxid则获取所有联系人的聊天记录数量
        :param MSG_db_path: MSG.db 文件路径
        :return: 聊天记录数量列表
        """
        if wxid:
            sql = f"SELECT StrTalker,COUNT(*) FROM MSG WHERE StrTalker='{wxid}';"
        else:
            sql = f"SELECT StrTalker, COUNT(*) FROM MSG GROUP BY StrTalker ORDER BY COUNT(*) DESC;"

        result = self.execute_sql(sql)
        df = pd.DataFrame(result, columns=["wxid", "chat_count"])
        # chat_counts ： {wxid: chat_count}
        chat_counts = df.set_index("wxid").to_dict()["chat_count"]
        return chat_counts

    def chat_count_total(self):
        """
        获取聊天记录总数
        :return: 聊天记录总数
        """
        sql = "SELECT COUNT(*) FROM MSG;"
        result = self.execute_sql(sql)
        if result and len(result) > 0:
            chat_counts = result[0][0]
            return chat_counts
        return 0

    # def room_user_list(self, selected_talker):
    #     """
    #     获取群聊中包含的所有用户列表
    #     :param MSG_db_path: MSG.db 文件路径
    #     :param selected_talker: 选中的聊天对象 wxid
    #     :return: 聊天用户列表
    #     """
    #     sql = (
    #         "SELECT localId, IsSender, StrContent, StrTalker, Sequence, Type, SubType,CreateTime,MsgSvrID,DisplayContent,CompressContent,BytesExtra,ROW_NUMBER() OVER (ORDER BY CreateTime ASC) AS id "
    #         "FROM MSG WHERE StrTalker=? "
    #         "ORDER BY CreateTime ASC")
    #
    #     result1 = self.execute_sql(sql, (selected_talker,))
    #     user_list = []
    #     read_user_wx_id = []
    #     for row in result1:
    #         localId, IsSender, StrContent, StrTalker, Sequence, Type, SubType, CreateTime, MsgSvrID, DisplayContent, CompressContent, BytesExtra, id = row
    #         bytes_extra = self.get_BytesExtra(BytesExtra)
    #         if bytes_extra:
    #             try:
    #                 talker = bytes_extra['3'][0]['2'].decode('utf-8', errors='ignore')
    #             except:
    #                 continue
    #         if talker in read_user_wx_id:
    #             continue
    #         user = get_contact(MSG_db_path, talker)
    #         if not user:
    #             continue
    #         user_list.append(user)
    #         read_user_wx_id.append(talker)
    #     return user_list

    # 单条消息处理
    def msg_detail(self, row):
        """
        获取单条消息详情,格式化输出
        """
        localId, IsSender, StrContent, StrTalker, Sequence, Type, SubType, CreateTime, MsgSvrID, DisplayContent, CompressContent, BytesExtra, id = row
        CreateTime = timestamp2str(CreateTime)

        type_id = (Type, SubType)
        type_name = typeid2name(type_id)

        content = {"src": "", "msg": StrContent}

        if type_id == (1, 0):  # 文本
            content["msg"] = StrContent

        elif type_id == (3, 0):  # 图片
            DictExtra = self.get_BytesExtra(BytesExtra)
            DictExtra_str = str(DictExtra)
            img_paths = [i for i in re.findall(r"(FileStorage.*?)'", DictExtra_str)]
            img_paths = sorted(img_paths, key=lambda p: "Image" in p, reverse=True)
            if img_paths:
                img_path = img_paths[0].replace("'", "")
                img_path = [i for i in img_path.split("\\") if i]
                img_path = os.path.join(*img_path)
                content["src"] = img_path
            else:
                content["src"] = ""
            content["msg"] = "图片"
        elif type_id == (34, 0):  # 语音
            tmp_c = xml2dict(StrContent)
            voicelength = tmp_c.get("voicemsg", {}).get("voicelength", "")
            transtext = tmp_c.get("voicetrans", {}).get("transtext", "")
            if voicelength.isdigit():
                voicelength = int(voicelength) / 1000
                voicelength = f"{voicelength:.2f}"
            content[
                "msg"] = f"语音时长：{voicelength}秒\n翻译结果：{transtext}" if transtext else f"语音时长：{voicelength}秒"
            content["src"] = os.path.join("audio", f"{StrTalker}",
                                          f"{CreateTime.replace(':', '-').replace(' ', '_')}_{IsSender}_{MsgSvrID}.wav")
        elif type_id == (43, 0):  # 视频
            DictExtra = self.get_BytesExtra(BytesExtra)
            DictExtra = str(DictExtra)

            DictExtra_str = str(DictExtra)
            video_paths = [i for i in re.findall(r"(FileStorage.*?)'", DictExtra_str)]
            video_paths = sorted(video_paths, key=lambda p: "mp4" in p, reverse=True)
            if video_paths:
                video_path = video_paths[0].replace("'", "")
                video_path = [i for i in video_path.split("\\") if i]
                video_path = os.path.join(*video_path)
                content["src"] = video_path
            else:
                content["src"] = ""
            content["msg"] = "视频"

        elif type_id == (47, 0):  # 动画表情
            content_tmp = xml2dict(StrContent)
            cdnurl = content_tmp.get("emoji", {}).get("cdnurl", "")
            if cdnurl:
                content = {"src": cdnurl, "msg": "表情"}

        elif type_id == (49, 0):
            DictExtra = self.get_BytesExtra(BytesExtra)
            url = match_BytesExtra(DictExtra)
            content["src"] = url
            file_name = os.path.basename(url)
            content["msg"] = file_name

        elif type_id == (49, 19):  # 合并转发的聊天记录
            CompressContent = self.decompress_CompressContent(CompressContent)
            content_tmp = xml2dict(CompressContent)
            title = content_tmp.get("appmsg", {}).get("title", "")
            des = content_tmp.get("appmsg", {}).get("des", "")
            recorditem = content_tmp.get("appmsg", {}).get("recorditem", "")
            recorditem = xml2dict(recorditem)
            content["msg"] = f"{title}\n{des}"
            content["src"] = recorditem

        elif type_id == (49, 57):  # 带有引用的文本消息
            CompressContent = self.decompress_CompressContent(CompressContent)
            content_tmp = xml2dict(CompressContent)
            appmsg = content_tmp.get("appmsg", {})
            title = appmsg.get("title", "")
            refermsg = appmsg.get("refermsg", {})
            displayname = refermsg.get("displayname", "")
            display_content = refermsg.get("content", "")
            display_createtime = refermsg.get("createtime", "")
            display_createtime = timestamp2str(
                int(display_createtime)) if display_createtime.isdigit() else display_createtime
            content["msg"] = f"{title}\n\n[引用]({display_createtime}){displayname}:{display_content}"
            content["src"] = ""

        elif type_id == (49, 2000):  # 转账消息
            CompressContent = self.decompress_CompressContent(CompressContent)
            content_tmp = xml2dict(CompressContent)
            feedesc = content_tmp.get("appmsg", {}).get("wcpayinfo", {}).get("feedesc", "")
            content["msg"] = f"转账：{feedesc}"
            content["src"] = ""

        elif type_id[0] == 49 and type_id[1] != 0:
            DictExtra = self.get_BytesExtra(BytesExtra)
            url = match_BytesExtra(DictExtra)
            content["src"] = url
            content["msg"] = type_name

        elif type_id == (50, 0):  # 语音通话
            content["msg"] = "语音/视频通话[%s]" % DisplayContent

        # elif type_id == (10000, 0):
        #     content["msg"] = StrContent
        # elif type_id == (10000, 4):
        #     content["msg"] = StrContent
        # elif type_id == (10000, 8000):
        #     content["msg"] = StrContent

        talker = "未知"
        if IsSender == 1:
            talker = "我"
        else:
            if StrTalker.endswith("@chatroom"):
                bytes_extra = self.get_BytesExtra(BytesExtra)
                if bytes_extra:
                    try:
                        talker = bytes_extra['3'][0]['2'].decode('utf-8', errors='ignore')
                        if "publisher-id" in talker:
                            talker = "系统"
                    except:
                        pass
            else:
                talker = StrTalker

        row_data = {"MsgSvrID": str(MsgSvrID), "type_name": type_name, "is_sender": IsSender, "talker": talker,
                    "room_name": StrTalker, "content": content, "CreateTime": CreateTime, "id": id}
        return row_data

    def msg_list(self, wxid="", start_index=0, page_size=500):
        if wxid:
            sql = (
                "SELECT localId, IsSender, StrContent, StrTalker, Sequence, Type, SubType,CreateTime,MsgSvrID,DisplayContent,CompressContent,BytesExtra,ROW_NUMBER() OVER (ORDER BY CreateTime ASC) AS id "
                "FROM MSG WHERE StrTalker=? "
                "ORDER BY CreateTime ASC LIMIT ?,?")
            result1 = self.execute_sql(sql, (wxid, start_index, page_size))
        else:
            sql = (
                "SELECT localId, IsSender, StrContent, StrTalker, Sequence, Type, SubType,CreateTime,MsgSvrID,DisplayContent,CompressContent,BytesExtra,ROW_NUMBER() OVER (ORDER BY CreateTime ASC) AS id "
                "FROM MSG ORDER BY CreateTime ASC LIMIT ?,?")
            result1 = self.execute_sql(sql, (start_index, page_size))

        # df = pd.DataFrame(result1, columns=[
        #     'localId', 'IsSender', 'StrContent', 'StrTalker', 'Sequence', 'Type', 'SubType', 'CreateTime', 'MsgSvrID',
        #     'DisplayContent', 'CompressContent', 'BytesExtra', 'id'
        # ])
        # df['msg_detail'] = df.apply(lambda row: self.msg_detail(row), axis=1)
        # return df['msg_detail'].tolist()

        data = []
        for row in result1:
            data.append(self.msg_detail(row))
        return data

        # return rdata


