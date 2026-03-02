-- Phase 1 local MySQL bootstrap
-- MySQL 8.x recommended

SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS `rrs_test_dev`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS `aml_new3`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_bin;

USE `aml_new3`;

DROP TABLE IF EXISTS `aml_f_sys_dict`;
DROP TABLE IF EXISTS `aml_f_sys_dict_type`;
DROP TABLE IF EXISTS `aml_f_wst_alert_cust_drft_record`;
DROP TABLE IF EXISTS `aml_f_wst_alert_cust_trans_info`;
DROP TABLE IF EXISTS `aml_f_tidb_model_result`;

CREATE TABLE `aml_f_sys_dict_type` (
  `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT COMMENT 'id',
  `code` varchar(50) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '主键',
  `code_name` varchar(30) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '展示用',
  `create_user` varchar(20) COLLATE utf8mb4_bin DEFAULT '' COMMENT '创建用户',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_user` varchar(20) COLLATE utf8mb4_bin DEFAULT '' COMMENT '更新用户',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '修改时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='字典类型表';

CREATE TABLE `aml_f_sys_dict` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '主键',
  `type_code` varchar(50) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '字典类型编码',
  `code_name` varchar(256) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '码值',
  `code_value` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '码值释义',
  `is_fixed` char(1) COLLATE utf8mb4_bin NOT NULL DEFAULT '0' COMMENT '是否修改0可以1不能',
  `create_user` varchar(20) COLLATE utf8mb4_bin DEFAULT '' COMMENT '创建用户',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_user` varchar(20) COLLATE utf8mb4_bin DEFAULT '' COMMENT '更新用户',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '修改时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `ind_typecode_codevalue` (`type_code`,`code_value`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='字典表';

CREATE TABLE `aml_f_tidb_model_result` (
  `uuid` varchar(64) NOT NULL COMMENT '主键id',
  `result_key` varchar(128) DEFAULT NULL COMMENT '模型主键+日期+cust_id',
  `model_key` varchar(64) DEFAULT NULL COMMENT '模型主键',
  `model_type` varchar(8) DEFAULT NULL COMMENT '模型类型:bh大额bs可疑',
  `cust_id` varchar(64) DEFAULT NULL COMMENT '模型客户号',
  `result_date` varchar(32) DEFAULT NULL COMMENT '模型结果日期',
  `cust_model_result` varchar(64) DEFAULT NULL COMMENT '模型结果',
  `model_seq` longtext DEFAULT NULL COMMENT '模型树结果序列化',
  `model_version` varchar(16) DEFAULT NULL COMMENT '模型版本',
  `ds` varchar(32) DEFAULT NULL COMMENT '数据日期',
  PRIMARY KEY (`uuid`),
  KEY `result_key_idx` (`result_key`),
  KEY `cust_id_idx` (`cust_id`),
  KEY `result_date_idx` (`result_date`),
  KEY `model_key_idx` (`model_key`),
  KEY `ds_idx` (`ds`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='模型结果bload过渡表';

CREATE TABLE `aml_f_wst_alert_cust_trans_info` (
  `uuid` varchar(64) NOT NULL COMMENT '主键',
  `cust_id` varchar(32) NOT NULL COMMENT '客户号',
  `model_key` varchar(10) NOT NULL COMMENT '模型主键',
  `alert_date` varchar(10) NOT NULL COMMENT '预警日期',
  `transactionkey` varchar(50) DEFAULT NULL COMMENT '交易流水号',
  `trans_time` datetime DEFAULT NULL COMMENT '交易时间',
  `cust_name` varchar(64) DEFAULT NULL COMMENT '客户名称',
  `receive_pay_cd` varchar(2) DEFAULT NULL COMMENT '资金收付表示',
  `trans_amount` decimal(20,4) DEFAULT NULL COMMENT '交易金额',
  `drft_no` varchar(64) DEFAULT NULL COMMENT '票号',
  `last_req_nm` varchar(64) DEFAULT NULL COMMENT '上手公司',
  `drwr_nm` varchar(64) DEFAULT NULL COMMENT '开票公司',
  `ds` varchar(32) DEFAULT NULL COMMENT '数据日期',
  PRIMARY KEY (`uuid`),
  KEY `cust_id_idx` (`cust_id`),
  KEY `model_key_idx` (`model_key`),
  KEY `alert_date_idx` (`alert_date`),
  KEY `trans_time_idx` (`trans_time`),
  KEY `ds_idx` (`ds`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='微闪贴预警客户进一个月交易信息';

CREATE TABLE `aml_f_wst_alert_cust_drft_record` (
  `uuid` varchar(64) NOT NULL COMMENT '主键',
  `cust_id` varchar(32) NOT NULL COMMENT '客户号',
  `model_key` varchar(10) NOT NULL COMMENT '模型主键',
  `alert_date` varchar(10) NOT NULL COMMENT '预警日期',
  `drft_no` varchar(64) DEFAULT NULL COMMENT '票号_子票开始区间_子票结束区间',
  `seq_no` varchar(8) DEFAULT NULL COMMENT '历史序号',
  `msg_typ` varchar(16) DEFAULT NULL COMMENT '交易类型',
  `req_nm` varchar(64) DEFAULT NULL COMMENT '请求方名称',
  `rcv_nm` varchar(64) DEFAULT NULL COMMENT '接收方名称',
  `sgn_up_dt` varchar(8) DEFAULT NULL COMMENT '签收时间',
  `ds` varchar(32) DEFAULT NULL COMMENT '数据日期',
  PRIMARY KEY (`uuid`),
  KEY `cust_id_idx` (`cust_id`),
  KEY `model_key_idx` (`model_key`),
  KEY `alert_date_idx` (`alert_date`),
  KEY `drft_no_idx` (`drft_no`),
  KEY `seq_no_idx` (`seq_no`),
  KEY `sgn_up_dt_idx` (`sgn_up_dt`),
  KEY `ds_idx` (`ds`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='微闪贴预警客户近一个月贴现票据的背书转让记录';

INSERT INTO `aml_f_sys_dict_type`
(`id`, `code`, `code_name`, `create_user`, `create_time`, `update_user`, `update_time`)
VALUES
(1108, 'receive_pay', '资金收付标志', 'rafelhuang', '2020-07-23 10:17:18', '', '2020-07-23 10:17:18');

INSERT INTO `aml_f_sys_dict`
(`id`, `type_code`, `code_name`, `code_value`, `is_fixed`, `create_user`, `create_time`, `update_user`, `update_time`)
VALUES
(13501, 'receive_pay', '收', '01', '0', 'rafelhuang', '2020-07-23 10:17:17', '', '2020-07-23 10:17:17'),
(13502, 'receive_pay', '付', '02', '0', 'rafelhuang', '2020-07-23 10:17:17', '', '2020-07-23 10:17:17');

INSERT INTO `aml_f_tidb_model_result`
(`uuid`, `result_key`, `model_key`, `model_type`, `cust_id`, `result_date`, `cust_model_result`, `model_seq`, `model_version`, `ds`)
VALUES
('01A819A45584B9957A0C8751CCD6B163', 'WSTY0012020-12-20962020122711000002', 'WSTY001', 'BS', '962020122711000002', '2020-12-20', '1', '20201220001', '1.0', '2020-12-20'),
('02A819A45584B9957A0C8751CCD6B164', 'WSTY0012020-11-259620220922110010', 'WSTY001', 'BS', '962020122711000002', '2020-11-25', '1', '20201125001', '1.0', '2020-11-25');

INSERT INTO `aml_f_wst_alert_cust_trans_info`
(`uuid`, `cust_id`, `model_key`, `alert_date`, `transactionkey`, `trans_time`, `cust_name`, `receive_pay_cd`, `trans_amount`, `drft_no`, `last_req_nm`, `drwr_nm`, `ds`)
VALUES
('11K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5', '962020122711000002', 'WSTY001', '2020-12-20', '2012100170247697657UC0FIQKKIU6TD-2', '2020-11-26 09:47:54', '辽宁麒麟湾体育公司', '付', 129876.4000, '510355201611120250722102158993_000009189488_0000093478', '深圳纸杯伈制造技忄有彡公司', '深圳纸杯誋制造技忄有彡公司', '2020-12-20'),
('10K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5', '962020122711000002', 'WSTY001', '2020-12-20', '2012100170247697657UC0FIQKKIU6TD-1', '2020-11-26 09:48:54', '辽宁麒麟湾体育公司', '收', 129876.4000, '510355201611120250722102158993_000009189488_0000093478', '深圳纸杯伈制造技忄有彡公司', '深圳纸杯誋制造技忄有彡公司', '2020-12-20'),
('31K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5', '962020122711000002', 'WSTY001', '2020-12-20', '2012100170247697657UC0FIQKKIU6TD-13', '2020-11-26 10:45:54', '辽宁麒麟湾体育公司', '付', 98765.4300, '510355201611120250722102158993_000009189488_0000093479', '北京天安科技公司', '上海浦东发展公司', '2020-12-20'),
('32K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5', '962020122711000002', 'WSTY001', '2020-12-20', '2012100170247697657UC0FIQKKIU6TD-14', '2020-11-26 10:49:54', '辽宁麒麟湾体育公司', '收', 98765.4300, '510355201611120250722102158993_000009189488_0000093479', '北京天安科技公司', '上海浦东发展公司', '2020-12-20'),
('33K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5', '962020122711000002', 'WSTY001', '2020-12-20', '2012100170247697657UC0FIQKKIU6TD-15', '2020-11-26 11:48:54', '辽宁麒麟湾体育公司', '付', 87654.3200, '510355201611120250722102158993_000009189488_0000093480', '广州白云贸易公司', '深圳南山科技公司', '2020-12-20'),
('34K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5', '962020122711000002', 'WSTY001', '2020-12-20', '2012100170247697657UC0FIQKKIU6TD-16', '2020-11-26 11:49:54', '辽宁麒麟湾体育公司', '收', 87654.3200, '510355201611120250722102158993_000009189488_0000093480', '广州白云贸易公司', '深圳南山科技公司', '2020-12-20'),
('35K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5', '962020122711000002', 'WSTY001', '2020-12-20', '2012100170247697657UC0FIQKKIU6TD-17', '2020-11-26 12:48:54', '辽宁麒麟湾体育公司', '付', 76543.2100, '510355201611120250722102158993_000009189488_0000093481', '杭州西湖电子公司', '宁波东海贸易公司', '2020-12-20'),
('36K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5', '962020122711000002', 'WSTY001', '2020-12-20', '2012100170247697657UC0FIQKKIU6TD-18', '2020-11-26 12:49:54', '辽宁麒麟湾体育公司', '收', 76543.2100, '510355201611120250722102158993_000009189488_0000093481', '杭州西湖电子公司', '宁波东海贸易公司', '2020-12-20'),
('37K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5', '962020122711000002', 'WSTY001', '2020-12-20', '2012100170247697657UC0FIQKKIU6TD-19', '2020-11-26 13:48:54', '辽宁麒麟湾体育公司', '付', 65432.1000, '510355201611120250722102158993_000009189488_0000093482', '成都天府投资公司', '重庆两江实业公司', '2020-12-20'),
('38K1L2M3N4O5P6Q7R8S9T0U1V2W3X4Y5', '962020122711000002', 'WSTY001', '2020-12-20', '2012100170247697657UC0FIQKKIU6TD-20', '2020-11-26 13:49:54', '辽宁麒麟湾体育公司', '收', 65432.1000, '510355201611120250722102158993_000009189488_0000093482', '成都天府投资公司', '重庆两江实业公司', '2020-12-20');

INSERT INTO `aml_f_wst_alert_cust_drft_record`
(`uuid`, `cust_id`, `model_key`, `alert_date`, `drft_no`, `seq_no`, `msg_typ`, `req_nm`, `rcv_nm`, `sgn_up_dt`, `ds`)
VALUES
('116BB52c09A87Sc108D9D32C3D1D242', '962020122711000002', 'WSTY001', '2020-12-20', '510355201611120250722102158993_000009189488_0000093478', '7', '背书', '大连上自称有限公司', '辽宁屿东城体育公司', '20200721', '2020-12-20'),
('026BB52c09A87Sc108D9D32C3D1D242', '962020122711000002', 'WSTY001', '2020-12-20', '510355201611120250722102158993_000009189488_0000093478', '8', '背书', '辽宁屿东城体育公司', '辽宁麒麟湾体育公司', '20200724', '2020-12-20'),
('GG6BB52c09A87Sc108D9D32C3D1D242', '962020122711000002', 'WSTY001', '2020-12-20', '510355201611120250722102158993_000009189488_0000093478', '9', '背书', '辽宁麒麟湾体育公司', '大连恒锐星体育公司', '20200724', '2020-12-20'),
('A1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6', '962020122711000002', 'WSTY001', '2020-12-20', '510355201611120250722102158993_000009189488_0000093478', '10', '背书', '北京天安科技公司', '上海浦东发展公司', '20200725', '2020-12-20'),
('B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7', '962020122711000002', 'WSTY001', '2020-12-20', '510355201611120250722102158993_000009189488_0000093478', '11', '背书', '广州白云贸易公司', '深圳南山科技公司', '20200726', '2020-12-20'),
('C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R8', '962020122711000002', 'WSTY001', '2020-12-20', '510355201611120250722102158993_000009189488_0000093478', '12', '背书', '杭州西湖电子公司', '宁波东海贸易公司', '20200727', '2020-12-20'),
('D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R8S9', '962020122711000002', 'WSTY001', '2020-12-20', '510355201611120250722102158993_000009189488_0000093478', '13', '背书', '成都天府投资公司', '重庆两江实业公司', '20200728', '2020-12-20'),
('E5F6G7H8I9J0K1L2M3N4O5P6Q7R8S9T0', '962020122711000002', 'WSTY001', '2020-12-20', '510355201611120250722102158993_000009189488_0000093478', '14', '背书', '武汉长江科技公司', '长沙湘江贸易公司', '20200729', '2020-12-20'),
('F6G7H8I9J0K1L2M3N4O5P6Q7R8S9T0U1', '962020122711000002', 'WSTY001', '2020-12-20', '510355201611120250722102158993_000009189488_0000093478', '15', '背书', '西安古城旅游公司', '兰州黄河实业公司', '20200730', '2020-12-20'),
('G7H8I9J0K1L2M3N4O5P6Q7R8S9T0U1V2', '962020122711000002', 'WSTY001', '2020-12-20', '510355201611120250722102158993_000009189488_0000093478', '16', '背书', '南京金陵电子公司', '苏州园林建设公司', '20200731', '2020-12-20');

USE `rrs_test_dev`;

DROP TABLE IF EXISTS `field_match_relations`;
DROP TABLE IF EXISTS `t_aml_f_import_info`;
DROP TABLE IF EXISTS `t_aml_sys_dict_info`;
DROP TABLE IF EXISTS `t_database_operation`;
DROP TABLE IF EXISTS `t_request_info`;

CREATE TABLE `t_request_info` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `trace_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '请求流水号（全局唯一标识）',
  `sysid` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '系统标识',
  `client_ip` varchar(45) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '客户端IP地址',
  `url` varchar(1024) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '请求URL',
  `method` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'HTTP方法',
  `headers` text COLLATE utf8mb4_unicode_ci COMMENT '请求头信息（JSON格式存储）',
  `query_params` text COLLATE utf8mb4_unicode_ci COMMENT '查询参数（JSON格式存储）',
  `request_body` longtext COLLATE utf8mb4_unicode_ci COMMENT '请求体内容',
  `page_url` varchar(1024) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '页面URL（来自X-Page-URL header）',
  `scenario_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '场景ID（来自X-Scenario-ID header）',
  `start_time` datetime NOT NULL COMMENT '请求开始时间',
  `start_time_ms` int(11) DEFAULT NULL COMMENT '执行开始毫秒时间',
  `end_time` datetime NOT NULL COMMENT '请求结束时间',
  `end_time_ms` int(11) DEFAULT NULL COMMENT '请求结束毫秒时间',
  `trace_stack_md5` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '调用链路追踪信息MD5',
  `status_code` int(11) DEFAULT NULL COMMENT '响应状态码',
  `response_body` longtext COLLATE utf8mb4_unicode_ci COMMENT '响应体内容',
  `duration` bigint(20) NOT NULL COMMENT '请求耗时（毫秒）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` tinyint(4) NOT NULL DEFAULT '0' COMMENT '是否删除（逻辑删除）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_trace_id` (`trace_id`),
  KEY `idx_url` (`url`(156)),
  KEY `idx_method` (`method`),
  KEY `idx_start_time` (`start_time`,`start_time_ms`),
  KEY `idx_end_time` (`end_time`,`end_time_ms`),
  KEY `idx_sysid` (`sysid`),
  KEY `idx_sysid_time` (`sysid`,`end_time`,`end_time_ms`),
  KEY `idx_client_ip` (`client_ip`),
  KEY `idx_trace_stack_md5` (`trace_stack_md5`),
  KEY `idx_request_info_trace_id` (`trace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='HTTP请求信息表';

CREATE TABLE `t_database_operation` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `trace_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '操作流水号（与请求关联）',
  `sysid` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '系统标识',
  `client_ip` varchar(45) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '客户端IP地址',
  `sequence` int(11) NOT NULL COMMENT '操作序号（在同一请求内的执行顺序）',
  `sql_text` longtext COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'SQL语句',
  `operation_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '操作类型（INSERT/UPDATE/DELETE/SELECT/OTHER）',
  `parameters` text COLLATE utf8mb4_unicode_ci COMMENT '参数绑定信息（JSON格式存储）',
  `result` text COLLATE utf8mb4_unicode_ci COMMENT '执行结果（JSON格式存储）',
  `query_result_data` longtext COLLATE utf8mb4_unicode_ci COMMENT '查询结果数据（对于SELECT操作，JSON格式存储）',
  `affected_rows` int(11) DEFAULT NULL COMMENT '影响行数（对于UPDATE/DELETE操作）',
  `result_rows` int(11) DEFAULT NULL COMMENT '查询结果行数（对于SELECT操作）',
  `start_time` datetime NOT NULL COMMENT '执行开始时间',
  `start_time_ms` int(11) DEFAULT NULL COMMENT '执行开始毫秒时间',
  `end_time` datetime NOT NULL COMMENT '执行结束时间',
  `end_time_ms` int(11) DEFAULT NULL COMMENT '请求结束毫秒时间',
  `trace_stack_md5` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '调用链路追踪信息MD5',
  `error_message` text COLLATE utf8mb4_unicode_ci COMMENT '异常信息（如果执行失败）',
  `data_source_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '数据源名称',
  `duration` bigint(20) NOT NULL COMMENT '执行耗时（毫秒）',
  `success` tinyint(1) NOT NULL DEFAULT '1' COMMENT '是否成功',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` tinyint(4) NOT NULL DEFAULT '0' COMMENT '是否删除（逻辑删除）',
  PRIMARY KEY (`id`),
  KEY `idx_trace_id` (`trace_id`,`sequence`),
  KEY `idx_operation_type` (`operation_type`),
  KEY `idx_start_time` (`start_time`,`start_time_ms`),
  KEY `idx_end_time` (`end_time`,`end_time_ms`),
  KEY `idx_sysid` (`sysid`,`operation_type`),
  KEY `idx_sysid_time` (`sysid`,`end_time`,`end_time_ms`),
  KEY `idx_success` (`success`),
  KEY `idx_create_time` (`create_time`),
  KEY `idx_client_ip` (`client_ip`),
  KEY `idx_trace_stack_md5` (`trace_stack_md5`),
  KEY `idx_database_operation_trace_id` (`trace_id`),
  KEY `idx_database_operation_trace_sequence` (`trace_id`,`sequence`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='数据库操作表';

CREATE TABLE `field_match_relations` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `target_table` varchar(100) COLLATE utf8mb4_bin NOT NULL,
  `target_field` varchar(100) COLLATE utf8mb4_bin NOT NULL,
  `source_table` varchar(100) COLLATE utf8mb4_bin NOT NULL,
  `source_field` varchar(100) COLLATE utf8mb4_bin NOT NULL,
  `match_reason` varchar(255) COLLATE utf8mb4_bin NOT NULL,
  `source_row_count` bigint(20) DEFAULT NULL,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

INSERT INTO `field_match_relations`
(`target_table`, `target_field`, `source_table`, `source_field`, `match_reason`, `source_row_count`)
VALUES
(
  'aml_f_wst_alert_cust_trans_info',
  'last_req_nm',
  'aml_f_wst_alert_cust_drft_record',
  'req_nm',
  'Seeded WST sample mapping: req_nm aligns with last_req_nm by draft chain.',
  10
),
(
  'aml_f_wst_alert_cust_trans_info',
  'drwr_nm',
  'aml_f_wst_alert_cust_drft_record',
  'rcv_nm',
  'Seeded WST sample mapping: rcv_nm aligns with drwr_nm by draft chain.',
  10
);

CREATE TABLE `t_aml_sys_dict_info` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `sys_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '系统表示',
  `db_col` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '表中字段',
  `mapping_col` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '映射码值字段',
  `status` varchar(8) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '生效状态:1-生效,0-失效',
  `create_user` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT '' COMMENT '创建用户',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_user` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT '' COMMENT '更新用户',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '修改时间',
  PRIMARY KEY (`id`),
  KEY `idx_db_col` (`db_col`),
  KEY `idx_mapping_col` (`mapping_col`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='反洗錢码值映射表';

CREATE TABLE `t_aml_f_import_info` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '主键',
  `type_code` varchar(50) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '字典类型编码',
  `type_name` varchar(30) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '字典类型编码类型名称',
  `code_name` varchar(256) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '码值',
  `code_value` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '码值释义',
  `is_fixed` char(1) COLLATE utf8mb4_bin NOT NULL DEFAULT '0' COMMENT '是否修改0可以1不能',
  `create_user` varchar(20) COLLATE utf8mb4_bin DEFAULT '' COMMENT '创建用户',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_user` varchar(20) COLLATE utf8mb4_bin DEFAULT '' COMMENT '更新用户',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '修改时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `ind_typecode_codevalue` (`type_code`,`code_value`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='自定义表';

INSERT INTO `t_aml_sys_dict_info`
(`id`, `sys_id`, `db_col`, `mapping_col`, `status`, `create_user`, `create_time`, `update_user`, `update_time`)
VALUES
(91, 'aml_web', 'acct_state', 'cust_acct_state', '1', 'init', '2025-11-21 14:23:22', 'init', '2025-11-21 14:23:22'),
(97, 'aml_web', 'acct_casa_flag', 'tb_fixed_flag', '1', 'init', '2025-11-21 14:23:22', 'init', '2025-11-21 14:23:22'),
(292, 'aml_web', 'actionflag', 'actionflag', '1', 'init', '2025-11-21 14:23:22', 'init', '2025-11-21 14:23:22'),
(401, 'aml_web', 'receive_pay_cd', 'receive_pay', '1', 'phase1', '2026-03-02 00:00:00', 'phase1', '2026-03-02 00:00:00');

INSERT INTO `t_aml_f_import_info`
(`id`, `type_code`, `type_name`, `code_name`, `code_value`, `is_fixed`, `create_user`, `create_time`, `update_user`, `update_time`)
VALUES
(1, 'receive_pay', '资金收付标识', '收', '01', '1', 'v_peterliu', '2025-11-21 15:04:33', 'v_peterliu', '2025-11-21 15:04:56'),
(2, 'receive_pay', '资金收付标识', '付', '02', '1', 'v_peterliu', '2025-11-21 15:04:33', 'v_peterliu', '2025-11-21 15:04:56');

INSERT INTO `t_request_info`
(`id`, `trace_id`, `sysid`, `client_ip`, `url`, `method`, `headers`, `query_params`, `request_body`, `page_url`, `scenario_id`, `start_time`, `start_time_ms`, `end_time`, `end_time_ms`, `trace_stack_md5`, `status_code`, `response_body`, `duration`, `create_time`, `update_time`, `deleted`)
VALUES
(3483, '907869950c9c40f487c7341e45641fed1760584971880', 'aml-web', '172.21.8.178', 'http://172.21.8.178:9982/aml/wst/custTransInfo?pageSize=10&pageNum=1', 'POST', '{}', '{"pageSize":"10","pageNum":"1"}', '{"custId":"962020122711000002","caseDate":"2020-12-27","modelNo":"WSTY001"}', 'http://172.21.8.178:9982/aml/#/taskManagement/caseReportTask/caseView/CBS20201227962020122711000002CNY/BS/962020122711000002/1/1/m2SuspiciousTaskDeal', NULL, '2025-10-16 11:22:51', 881, '2025-10-16 11:22:52', 286, '02600d23b986a36b189596fc456cf7f6', 200, '{"success":true}', 405, '2025-10-16 11:22:55', '2025-10-16 11:22:55', 0),
(3481, '4bb8309878e4426ebce5b579b82505b81760584971882', 'aml-web', '172.21.8.178', 'http://172.21.8.178:9982/aml/wst/custDrftRecord?pageSize=10&pageNum=1', 'POST', '{}', '{"pageSize":"10","pageNum":"1"}', '{"custId":"962020122711000002","caseDate":"2020-12-27","modelNo":"WSTY001"}', 'http://172.21.8.178:9982/aml/#/taskManagement/caseReportTask/caseView/CBS20201227962020122711000002CNY/BS/962020122711000002/1/1/m2SuspiciousTaskDeal', NULL, '2025-10-16 11:22:51', 883, '2025-10-16 11:22:52', 275, '02600d23b986a36b189596fc456cf7f6', 200, '{"success":true}', 392, '2025-10-16 11:22:54', '2025-10-16 11:22:54', 0);

INSERT INTO `t_database_operation`
(`id`, `trace_id`, `sysid`, `client_ip`, `sequence`, `sql_text`, `operation_type`, `parameters`, `result`, `query_result_data`, `affected_rows`, `result_rows`, `start_time`, `start_time_ms`, `end_time`, `end_time_ms`, `trace_stack_md5`, `error_message`, `data_source_name`, `duration`, `success`, `create_time`, `update_time`, `deleted`)
VALUES
(58016, '907869950c9c40f487c7341e45641fed1760584971880', 'aml-web', '172.21.8.178', 1, 'SELECT  uuid,result_key,model_key,model_type,cust_id,result_date,cust_model_result,model_seq,model_version  FROM aml_f_tidb_model_result      WHERE  (cust_id = ''962020122711000002'' AND result_date <= ''2020-12-27'' AND model_key = ''WSTY001'')', 'SELECT', '{"?1":"962020122711000002","?2":"2020-12-27","?3":"WSTY001"}', 'true', '{"rowCount":2}', -1, 2, '2025-10-16 11:22:51', 881, '2025-10-16 11:22:52', 186, '5c77476d4221964be6079feb393e4ee2', NULL, NULL, 305, 1, '2025-10-16 11:22:55', '2025-10-16 11:22:55', 0),
(58017, '907869950c9c40f487c7341e45641fed1760584971880', 'aml-web', '172.21.8.178', 2, 'SELECT COUNT(*) AS total FROM aml_f_wst_alert_cust_trans_info WHERE (cust_id = ''962020122711000002'' AND model_key = ''WSTY001'' AND alert_date = ''2020-12-20'')', 'SELECT', '{"?1":"962020122711000002","?2":"WSTY001","?3":"2020-12-20"}', 'true', '{"rowCount":1}', -1, 1, '2025-10-16 11:22:51', 881, '2025-10-16 11:22:52', 234, 'e6971b18ac3b6f6f120fb1abf311251f', NULL, NULL, 353, 1, '2025-10-16 11:22:55', '2025-10-16 11:22:55', 0),
(58018, '907869950c9c40f487c7341e45641fed1760584971880', 'aml-web', '172.21.8.178', 3, 'SELECT  uuid,cust_id,model_key,alert_date,transactionkey,trans_time,cust_name,receive_pay_cd,trans_amount,drft_no,last_req_nm,drwr_nm  FROM aml_f_wst_alert_cust_trans_info      WHERE  (cust_id = ''962020122711000002'' AND model_key = ''WSTY001'' AND alert_date = ''2020-12-20'') ORDER BY trans_time ASC LIMIT 10', 'SELECT', '{"?1":"962020122711000002","?2":"WSTY001","?3":"2020-12-20","?4":10}', 'true', '{"rowCount":10}', -1, 10, '2025-10-16 11:22:51', 881, '2025-10-16 11:22:52', 280, '9ac5a6f23c816d69cf118cf069b2ab9e', NULL, NULL, 399, 1, '2025-10-16 11:22:55', '2025-10-16 11:22:55', 0),
(58010, '4bb8309878e4426ebce5b579b82505b81760584971882', 'aml-web', '172.21.8.178', 1, 'SELECT  uuid,result_key,model_key,model_type,cust_id,result_date,cust_model_result,model_seq,model_version  FROM aml_f_tidb_model_result      WHERE  (cust_id = ''962020122711000002'' AND result_date <= ''2020-12-27'' AND model_key = ''WSTY001'')', 'SELECT', '{"?1":"962020122711000002","?2":"2020-12-27","?3":"WSTY001"}', 'true', '{"rowCount":2}', -1, 2, '2025-10-16 11:22:51', 883, '2025-10-16 11:22:52', 182, '51aee1af3cb14816b24ed66cfad7a7b6', NULL, NULL, 299, 1, '2025-10-16 11:22:54', '2025-10-16 11:22:54', 0),
(58011, '4bb8309878e4426ebce5b579b82505b81760584971882', 'aml-web', '172.21.8.178', 2, 'SELECT COUNT(*) AS total FROM aml_f_wst_alert_cust_drft_record WHERE (cust_id = ''962020122711000002'' AND model_key = ''WSTY001'' AND alert_date = ''2020-12-20'')', 'SELECT', '{"?1":"962020122711000002","?2":"WSTY001","?3":"2020-12-20"}', 'true', '{"rowCount":1}', -1, 1, '2025-10-16 11:22:51', 883, '2025-10-16 11:22:52', 229, '600248f68f2b235825dee79310bd4ccb', NULL, NULL, 346, 1, '2025-10-16 11:22:54', '2025-10-16 11:22:54', 0),
(58012, '4bb8309878e4426ebce5b579b82505b81760584971882', 'aml-web', '172.21.8.178', 3, 'SELECT  uuid,cust_id,model_key,alert_date,drft_no,seq_no,msg_typ,req_nm,rcv_nm,sgn_up_dt  FROM aml_f_wst_alert_cust_drft_record      WHERE  (cust_id = ''962020122711000002'' AND model_key = ''WSTY001'' AND alert_date = ''2020-12-20'') order by  drft_no  asc , CAST(seq_no  AS SIGNED) asc, sgn_up_dt asc LIMIT 10', 'SELECT', '{"?1":"962020122711000002","?2":"WSTY001","?3":"2020-12-20","?4":10}', 'true', '{"rowCount":10}', -1, 10, '2025-10-16 11:22:51', 883, '2025-10-16 11:22:52', 272, '1308eeba91056fd99847a51a45525a46', NULL, NULL, 389, 1, '2025-10-16 11:22:54', '2025-10-16 11:22:54', 0);
