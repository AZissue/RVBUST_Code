import os
import pandas as pd

class DataManager:
    def __init__(self):
        self.current_excel_path = self.get_default_excel_path()
    
    def get_default_excel_path(self):
        """获取默认Excel文件路径"""
        data_dir = "d:\\WorkLog Pro\\data"
        return os.path.join(data_dir, "worklog.xlsx")
    
    def get_excel_file_path(self):
        """获取Excel文件路径"""
        return self.current_excel_path
    
    def set_excel_file_path(self, path):
        """设置Excel文件路径"""
        self.current_excel_path = path
    
    def load_data_from_excel(self):
        """从Excel文件加载数据"""
        file_path = self.get_excel_file_path()
        
        try:
            if os.path.exists(file_path):
                df = pd.read_excel(file_path)
                return df
            else:
                return None
        except Exception as e:
            raise Exception(f"加载Excel文件失败: {str(e)}")
    
    def save_data_to_excel(self, data):
        """保存数据到Excel文件"""
        file_path = self.get_excel_file_path()
        
        try:
            df = pd.DataFrame(data)
            df.to_excel(file_path, index=False)
            return True
        except Exception as e:
            raise Exception(f"保存Excel文件失败: {str(e)}")
    
    def import_data_from_excel(self, file_path):
        """从指定Excel文件导入数据"""
        try:
            df = pd.read_excel(file_path)
            self.set_excel_file_path(file_path)
            return df
        except Exception as e:
            raise Exception(f"导入Excel文件失败: {str(e)}")
    
    def export_data_to_excel(self, data, file_path):
        """导出数据到指定Excel文件"""
        try:
            df = pd.DataFrame(data)
            df.to_excel(file_path, index=False)
            return True
        except Exception as e:
            raise Exception(f"导出Excel文件失败: {str(e)}")
