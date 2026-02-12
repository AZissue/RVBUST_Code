class BusinessLogic:
    def __init__(self):
        pass
    
    def generate_new_id(self, existing_records):
        """生成新的记录ID"""
        if not existing_records:
            return 1
        
        max_id = 0
        for record in existing_records:
            try:
                record_id = int(record.get('ID', 0))
                if record_id > max_id:
                    max_id = record_id
            except:
                pass
        
        return max_id + 1
    
    def validate_record(self, record):
        """验证记录数据"""
        # 客户名称已设置为选填内容
        
        return True
    
    def prepare_record_for_table(self, record):
        """准备记录数据用于表格显示"""
        # 保持完整内容，不添加省略号
        problem = record.get('problem', '')
        solution = record.get('solution', '')
        
        # 只显示前一段字符，不添加省略号
        max_length = 30
        if len(problem) > max_length:
            problem = problem[:max_length]
        if len(solution) > max_length:
            solution = solution[:max_length]
        
        return {
            'ID': record.get('ID'),
            '日期': record.get('date'),
            '客户名称': record.get('customer'),
            '相机型号': record.get('camera'),
            '客户问题': problem,
            '解决方法': solution,
            '问题类型': record.get('type'),
            '问题进度': record.get('status')
        }
    
    def format_record_from_form(self, form_data, record_id=None):
        """格式化表单数据为记录格式"""
        record = {
            'ID': record_id if record_id else None,
            'date': form_data.get('date'),
            'customer': form_data.get('customer'),
            'camera': form_data.get('camera'),
            'problem': form_data.get('problem'),
            'solution': form_data.get('solution'),
            'type': form_data.get('type'),
            'status': form_data.get('status')
        }
        
        return record
    
    def sort_records(self, records, key, reverse=False):
        """排序记录"""
        if not records:
            return []
        
        try:
            sorted_records = sorted(records, key=lambda x: x.get(key, ''), reverse=reverse)
            return sorted_records
        except:
            return records
    
    def search_records(self, records, keyword):
        """搜索记录"""
        if not keyword:
            return records
        
        keyword = keyword.lower()
        matched_records = []
        unmatched_records = []
        
        for record in records:
            match = False
            search_fields = ['customer', 'camera', 'problem', 'solution']
            
            for field in search_fields:
                if keyword in str(record.get(field, '')).lower():
                    match = True
                    break
            
            if match:
                matched_records.append(record)
            else:
                unmatched_records.append(record)
        
        return matched_records, unmatched_records
