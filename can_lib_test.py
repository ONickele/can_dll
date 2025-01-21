import ctypes
from ctypes import c_char_p, c_int, c_void_p,c_ubyte, POINTER
from ctypes import util
import os
from cffi import FFI
import struct
import numpy as np
import threading
import paramiko
import logging

import datetime
import time
import struct

# Создаем логгер
logger = logging.getLogger("my_logger")
logger.setLevel(logging.DEBUG)  # Устанавливаем общий уровень логгера

# Формат сообщений
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Обработчик для консоли (выводит все сообщения)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)  # Уровень для консоли — все сообщения
console_handler.setFormatter(formatter)

# Обработчик для файла (только ERROR и CRITICAL)
file_handler = logging.FileHandler("errors.log", mode='a')
file_handler.setLevel(logging.ERROR)  # Уровень для файла — только ERROR и CRITICAL
file_handler.setFormatter(formatter)

# Добавляем обработчики к логгеру
logger.addHandler(console_handler)
logger.addHandler(file_handler)


TYPES_MAP = {
    'uint8':('B',1),
    'uint16': ('H',2),
    'uint32': ('I',4),
    'uint64': ('Q',8),
    'float32': ('f',4),
    'float64': ('d',8),
}

CALLBACK_FUNC = ctypes.CFUNCTYPE(None,POINTER(c_ubyte))

# загружаем dll
def load_dll(name_dll: str) -> int:
    """
    Загружает DLL библиотеку.

    @param name_dll: Путь к DLL файлу.
    @return: Загруженная библиотека или код ошибки (-1 - не найдена, -2 - ошибка загрузки функций, 1 - успешно).
    """
    dll_path = None
    dll_path_lib = None

    #Проверяем что dll на месте
    dll_path = os.path.abspath(name_dll)
    if dll_path:
        dll_path_lib = util.find_library(dll_path)
    else:
        logger.error("DLL не найдена, проверьте путь.")
        return -1
    if dll_path_lib:
        #Подгружаем dll сначала через FFI чтобы не было проблем с классами и потоками
        ffi = FFI()
        ffiobj = ffi.dlopen(dll_path)
        dll = ctypes.cdll.LoadLibrary(dll_path_lib)
        if load_functions(dll) == 1:
            return dll
        else:
            return -2
    else:
        logger.error("DLL не найдена, проверьте путь и зависимости.")
        return -1

def load_functions(dll : ctypes.CDLL) -> int:
    """
    Устанавливает типы аргументов и возвращаемых значений для функций из DLL.

    @param dll: Экземпляр загруженной DLL библиотеки.
    @return: 1, если функции успешно настроены, -1 в случае если передали не ctypes.CDLL.
    """

    if isinstance(dll,ctypes.CDLL):
        # Установка типов аргументов и возвращаемых значений для функций
        dll.CreateWorker.restype = POINTER(c_void_p)

        dll.DestroyWorker.argtypes = [POINTER(c_void_p)]

        dll.CreateSocket.argtypes = [POINTER(c_void_p)]
        dll.CreateSocket.restype = c_int

        dll.ConnectToUDPServer.argtypes = [POINTER(c_void_p), c_char_p, c_int]
        dll.ConnectToUDPServer.restype = c_int

        dll.WriteSDO.argtypes = [POINTER(c_void_p), c_int, c_int, c_int, POINTER(c_ubyte), c_int, c_int]
        dll.WriteSDO.restype = c_int

        dll.ReadSDO.argtypes = [POINTER(c_void_p), c_int, c_int, c_int, POINTER(c_ubyte), c_int]
        dll.ReadSDO.restype = c_int

        dll.WritePDO.argtypes = [POINTER(c_void_p), c_int, c_int, POINTER(c_ubyte), c_int]
        dll.WritePDO.restype = c_int

        dll.Start_heartbeat.argtypes = [POINTER(c_void_p), c_int]
        dll.Start_heartbeat.restype = c_int

        dll.Stop_heartbeat.argtypes = [POINTER(c_void_p)]
        dll.Stop_heartbeat.restype = c_int

        
        dll.RegisterCallback_pdo.argtypes = [POINTER(c_void_p), CALLBACK_FUNC]

        dll.RegisterCallback_error.argtypes = [POINTER(c_void_p), CALLBACK_FUNC]

        dll.Disconnect.argtypes = [POINTER(c_void_p)]
        dll.Disconnect.restype = c_int
        return 1
    else:
        logger.error("Ошибка проверки типа входа функции load_dll")
        return -1




def number_to_bytes(value: {int|float}, dtype: str) -> tuple[int, bytearray]:
    if dtype not in TYPES_MAP: return -1, b''
    fmt, size = TYPES_MAP[dtype]
    try:
        raw_bytes = struct.pack(fmt, value)
        if len(raw_bytes) < size:
            return 1, raw_bytes.ljust(size, b'\x00')  # Дополняем нулями справа
        else:
            return 1, raw_bytes
    except struct.error as e:
        logger.error(f"Ошибка преобразования числа: {e}")
        return -2, b''


def is_convertible_to_float32(value : float) -> bool:
    """
    Проверяет, можно ли преобразовать значение в тип float32.

    @param value: Значение для проверки.
    @return: True, если преобразование возможно, иначе False.
    """

    try:
        # Пробуем преобразовать значение в float32
        np.float32(value)
        return True
    except (OverflowError, ValueError) as e:
        logger.error(f"Ошибка преобразования числа типа float: {e}")
        return False

class CanWorker():
    def __init__(self, dll: ctypes.CDLL, pdo_objects: dict, ssh_ip: str, ssh_port: int=22, usr: str='root', psw: str='1'):
        """
            Класс для работы с CAN-устройствами через DLL библиотеку.

            @param dll: Экземпляр загруженной DLL.
            @param pdo_objects: Словарь с описанием PDO (Process Data Object).
            @param pdo_buffer: Буфер для получения PDO.
            @param ssh_ip: IP-адрес для подключения по SSH.
            @param ssh_port: Порт для SSH подключения.
            @param usr: Имя пользователя для SSH.
            @param psw: Пароль пользователя для SSH.
        """
        
        self.dll = dll
        self.worker_instance = self.dll.CreateWorker() # создаем экземпляр класса Worker для работы с сокетом
        self.isConnected = False # флаг наличия подключения

        self.pdo_objects = pdo_objects # записываем наши ожидаемые PDO 
        self.pdo_cobids=pps.keys() # записываем нужные cobid 

        self.__ip = ssh_ip
        self.___port = ssh_port
        self.__usr = usr
        self.__psw = psw

        self.callback_func = None
        self.callback_func_error = None

    def __del__(self):
        """
        Деструктор, уничтожает экземпляр Worker в dll при удалении объекта.
        """
        self.dll.DestroyWorker(self.worker_instance)

    def __sshconnect(self, port: int) -> int:
        """
        Устанавливает SSH-соединение для запуска socat и отключения nftables.

        @param port: Порт для подключения по SSH.
        @return: 1 если подключение успешно, -1 в случае ошибки.
        """

        self.__shhclient=paramiko.SSHClient()
        self.__shhclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            logger.info(f"Подключаемся к ПЛК по ssh на порт {port}")
            
            self.__shhclient.connect(hostname=self.__ip, username=self.__usr, password=self.__psw, port=self.___port)
            #if self.__check_socat('nftables') < 0:
            logger.info(f"Отключаем nftables")
            stdin, stdout, stderr = self.__shhclient.exec_command('systemctl stop nftables') # 🥂🥂 рубим сетевой экран нахой он нам не нужон 🥂🥂
            time.sleep(2)
            if self.__check_socat('socat') < 0:
                logger.info(f"Включаем socat")
                stdin, stdout, stderr = self.__shhclient.exec_command(f'socat INTERFACE:can0,pf=29,type=3,prototype=1 UDP-LISTEN:{port},fork')  # 🥂🥂 запускаем socat can->UDP 🥂🥂
            self.__shhclient.close()
            time.sleep(3)
            return 1
        except Exception as e:
            logger.error(f"Не удалось подключиться к ПЛК исключение: \n{e}")
            return -1

    def __check_socat(self, port) -> int:
        """
        Проверяет, запущен ли socat на устройстве.
        """
        try:
            stdin, stdout, stderr = self.__shhclient.exec_command(f'ps -ef|grep socat |grep {port}')
            if 'socat INTERFACE:can0,pf=29,type=3,prototype=1 UDP-LISTEN' in str(stdout.read()).split('        ')[1]:
                return 1
            else:
                return -1
        except Exception as e:
            print(e)
            return -2


    def connect(self, ip_address: str, port: int) -> int:
        """
        Основная функция подключения к устройству. При первой неудачной попытке подключения, пробует отключить nftables и запустить socat.

        @param ip_address: IP-адрес устройства.
        @param port: Порт для подключения.
        @return: 1 если подключение успешно, -1 в случае ошибки.
        """

        count = 0
        max_count = 3
        while count<= max_count:
            # пробуем установить udp подключение
            logger.info(f"Попытка {count + 1} подключения к ПЛК")
            if self.connect_to_udp_server(ip_address, port)>0:
                logger.info("подключились к ПЛК")
                return 1
            else:
                # если не получилось пробуем отрубить nftables и запустить сокат
                logger.error(f"Не удалось подключиться к ПЛК, попытка {count + 1} из {max_count}")
                if self.__sshconnect(port)<0:
                    return -1
            count+=1
        else:
            return -1

    def connect_to_udp_server(self, ip_address: str, port: int) -> int:
        """
        Подключение к UDP серверу.

        @param ip_address: IP-адрес сервера.
        @param port: Порт сервера.
        @return: 1 если подключение успешно, -1 в случае ошибки, -2 если уже подключено.
        """

        if self.isConnected: return -2

        if (self.dll.CreateSocket(self.worker_instance) > 0):
            res = self.dll.ConnectToUDPServer(self.worker_instance, ip_address.encode('utf-8'), port)
            if res > 0:
                self.isConnected = True
            return res
        else:
            return -1

    def WriteSDO(self,node_id: int, index: int, sub_index: int, data:int | float, data_type: str, timeout_ms: int) -> int:
        """
        Записывает данные в объект SDO (Service Data Object).

        @param node_id: Идентификатор узла.
        @param index: Индекс объекта.
        @param sub_index: Подиндекс объекта.
        @param data: Данные для записи (целое или вещественное число).
        @param data_type: Тип данных ('uint8', 'uint16', 'uint32', 'float32').
        @param timeout_ms: Время ожидания в миллисекундах.
        @return: Код результата (1 - успешно -1 - не подключены -2 - ошибка записи -4 нет ответа, -5 - данные не помещаются в тип)
        """
        if not self.isConnected: return -2
        packaging_error = False
        match data_type:
            case 'uint8':
                if data <= 0xFF: # проверяем что данные поместятся при преобразовании 
                    data_send = (c_ubyte * 1)(*data.to_bytes(1, byteorder='little'))
                    data_size = 1
                else:
                    packaging_error = True
            case 'uint16':
                if data <= 0xFFFF: # проверяем что данные поместятся при преобразовании 
                    data_send = (c_ubyte * 2)(*data.to_bytes(2, byteorder='little'))
                    data_size = 2
                else:
                    packaging_error = True
            case 'uint32':
                if data <= 0xFFFFFFFF: # проверяем что данные поместятся при преобразовании 
                    data_send = (c_ubyte * 4)(*data.to_bytes(4, byteorder='little'))
                    data_size = 4
                else:
                    packaging_error = True
            case 'float32': 
                if is_convertible_to_float32(data): # проверяем что данные поместятся при преобразовании 
                    data_send=bytearray(struct.pack("f", data))
                    data_size = 4
                else:
                    packaging_error = True
                
        if packaging_error:
            logger.error(f"Ошибка упаковки данных в пакет значение:{data} тип:{data_type}")
        write_result = self.dll.WriteSDO(self.worker_instance, node_id, index, sub_index, data_send, data_size, timeout_ms)
        return write_result
    
    def ReadSDO(self, node_id: int, index: int, sub_index: int, timeout_ms: int) -> int | float:
        """
        Читает данные из объекта SDO.

        @param node_id: Идентификатор узла.
        @param index: Индекс объекта.
        @param sub_index: Подиндекс объекта.
        @param timeout_ms: Время ожидания в миллисекундах.
        @return: Прочитанные данные или код ошибки.
        """

        if not self.isConnected: return -2

        buffer = (c_ubyte * 5)()
        read_result = self.dll.ReadSDO(self.worker_instance, node_id, index, sub_index, buffer, timeout_ms)
        if read_result > 0:
            len_data = (buffer[0] ^ 0x43)>>2
            return int.from_bytes(buffer[1:len_data+1], "little")

        else:
            return read_result

    def WritePDO(self, node_id: int, number_pdo: int, pdo_data: c_ubyte):
        """
        Запись PDO пакета в шину
        """
        if not self.isConnected: return -2

        data_size=len(pdo_data)
        res = dll.WritePDO(self.worker_instance, node_id, number_pdo, pdo_data, data_size)
        return res

    def Stop_ReadPDO(self,th : threading.Thread) -> int:
        """
        Останавливает процесс чтения PDO.

        @param th: Поток для остановки.
        """
        self.dll.Stop_ReadPDO(self.worker_instance)
        if th.is_alive():
            logger.info("Поток чтения PDO остановлен")
            th.join()
        else:
            logger.warning("Поток чтения PDO не запущен")
            return -1

    def parse_pdo(self, data: c_ubyte): # 🥂🥂 чтение pdo 🥂🥂
        """
        Парсит данные из PDO.

        @param data: Данные из PDO (cobid и payload).
        @return: Кортеж из номера узла, COBID и параметров.
        """
        if data[0] != 0:
            bytes_v=0 #🥂🥂 какие байты мы проверили в пакете 🥂🥂
            params=[]
            cobid = int.from_bytes(data[0:2], "little") # вычисляем cobid
            number_pdo = cobid & 0x780 # смотрим какой  номер PDO
            node=cobid - number_pdo
            if cobid in self.pdo_cobids:
                if data[2]==int(sum(self.pdo_objects[cobid]['mapping'])/8):
                    values=data[3:]
                    for i,l in enumerate(self.pdo_objects[cobid]['mapping']): # 🥂🥂 i-номер чанка l-длина чанка 🥂🥂
                        count=int(l/8)
                        a = self.pdo_objects[cobid]['data_types']
                        type_ch=self.pdo_objects[cobid]['data_types'][i]

                        match type_ch:
                            case 'uint8':
                                params.append(values[bytes_v])
                            case 'uint16':
                                params.append(int.from_bytes(values[bytes_v:bytes_v+count], "little", signed=False))
                            case 'uint32': 
                                params.append(int.from_bytes(values[bytes_v:bytes_v+count], "little", signed=False))
                            case 'float32':
                                params.append(struct.unpack('<f',bytes(values[bytes_v:bytes_v+count]))[0])
                        bytes_v+=count
                else:
                    logger.error(f"ошибка в длинне пакета ожидалось {int(sum(self.pdo_objects[cobid]['mapping'])/8)} пришло {data[2]}")
                return node, hex(number_pdo), params
            else:
                logger.debug(f"PDO node:{node} number:{hex(number_pdo)} нет в списке маппированных")
          
    def packing_pdo(self, mapping:dict, data: list) -> tuple[int,c_ubyte]:
        """
        Упаковка данных в PDO.
        @param data: Данные для упаковки.
        @return: Данные для отправки PDO.
        """
        if not len(data) == len(mapping['data_types']):  return -1,(c_ubyte * 8)()
        payload=b''
        target_len = 0
        packing_error = False
        for n,value in enumerate(data):
            type_value = mapping['data_types'][n]
            #res ,value = number_to_bytes(value,type_value)
            match type_value:
                case 'uint8':
                    if value <= 0xFF: # проверяем что данные поместятся при преобразовании 
                        data_send = (c_ubyte * 1)(*value.to_bytes(1, byteorder='little'))
                    else:
                        return -3,(c_ubyte * 8)()
                case 'uint16':
                    if value <= 0xFFFF: # проверяем что данные поместятся при преобразовании 
                        data_send = (c_ubyte * 2)(*value.to_bytes(2, byteorder='little'))
                    else:
                        return -3,(c_ubyte * 8)()
                case 'uint32':
                    if value <= 0xFFFFFFFF: # проверяем что данные поместятся при преобразовании 
                        data_send = (c_ubyte * 4)(*value.to_bytes(4, byteorder='little'))
                    else:
                        return -3,(c_ubyte * 8)()
                case 'float32': 
                    if is_convertible_to_float32(value): # проверяем что данные поместятся при преобразовании 
                        data_send=(c_ubyte * 4)(bytearray(struct.pack("f", value)))
                    else:
                        return -3,(c_ubyte * 8)()
            if packing_error:
                logger.error(f"Ошибка упаоквки данных в PDO пакет значение {value} тип {type_value}")
                return -3,(c_ubyte * 8)()
            target_len += TYPES_MAP[type_value][1]
            payload+=data_send
        logger.debug(f"Payload DPO {payload}")
        if len(payload) == target_len:
            return 1,(c_ubyte * 8)(*(payload))
        else:
            return -2,(c_ubyte * 8)()


    def get_pdo(self, pdo):
        length = 11
        pointer_to_array = ctypes.cast(pdo, ctypes.POINTER(ctypes.c_ubyte))
        data = (ctypes.c_ubyte * length).from_address(ctypes.addressof(pointer_to_array.contents))
        res=a.parse_pdo(data)
        if res:
            print(res)

    def get_error(self,erorr):
        length = 10
        pointer_to_array = ctypes.cast(erorr, ctypes.POINTER(ctypes.c_ubyte))
        data = bytearray(pointer_to_array[i] for i in range(length))
        logger.error(f"Ошибка на шине {data}")

    def register_callbac_pdo(self,func):
        dll.RegisterCallback_pdo(self.worker_instance,func)

    def register_callbac_error(self,func):
        dll.RegisterCallback_error(self.worker_instance,func)

    def Start_heartbeat(self, period_ms:int):
        """
        Запускает выдачу hearbeat
        """
        if not self.isConnected: return -2
        
        res=self.dll.Start_heartbeat(self.worker_instance, period_ms)
        return res
    
    def Stop_heartbeat(self):
        """
        Останавливает выдачу hearbeat
        """
        if not self.isConnected: return -2
        
        res=self.dll.Stop_heartbeat(self.worker_instance)
        return res
    def Disconnect(self):
        """
        Отключает соединение и ставит  флаг isConnected в False..
        """
        if not self.isConnected: return -2

        self.dll.Disconnect(self.worker_instance)
        self.isConnected = False
    
    def DestroyWorker(self):
        """
        Уничтожает экземпляр Worker и очищает ресурсы.
        """
        self.dll.DestroyWorker(self.worker_instance)
    
pps={#0x18C:{'mapping':[8,8,8,8,32],'data_types':['uint8','uint8','uint8','uint8','float32']},
     #0x181:{'mapping':[16,16,16,16],'data_types':['uint16','uint16','uint16','uint16']},
     #0x281:{'mapping':[16,16,16,16],'data_types':['uint16','uint16','uint16','uint16']},
     0x195:{'mapping':[16,16,16,16],'data_types':['uint16','uint16','uint16','uint16']},
     0x295:{'mapping':[16,16,16,16],'data_types':['uint16','uint16','uint16','uint16']},
     0x395:{'mapping':[16,16,16,16],'data_types':['uint16','uint16','uint16','uint16']},
     0x495:{'mapping':[16,16,16,16],'data_types':['uint16','uint16','uint16','uint16']},
     0x18B:{'mapping':[16,8,16],'data_types':['uint16','uint8','uint16']},
     0x28B:{'mapping':[8,8,8,8],'data_types':['uint8','uint8','uint8','uint8']},
     0x18D:{'mapping':[16,8,16],'data_types':['uint16','uint8','uint16']},
     0x28D:{'mapping':[8,8,8,8],'data_types':['uint8','uint8','uint8','uint8']},
     0x18E:{'mapping':[16,8,16],'data_types':['uint16','uint8','uint16']},
     0x28E:{'mapping':[8,8,8,8],'data_types':['uint8','uint8','uint8','uint8']},
     0x391:{'mapping':[16,16,16,16],'data_types':['uint16','uint16','uint16','uint16']},
     0x491:{'mapping':[16,16,16,16],'data_types':['uint16','uint16','uint16','uint16']},
     0x511:{'mapping':[8,8,8,8,8],'data_types':['uint8','uint8','uint8','uint8','uint8']},
     0x18A:{'mapping':[8,8,8,8,32],'data_types':['uint8','uint8','uint8','uint8','float32']},
    }


if __name__=="__main__":
    ppw={0x200:{'data_types':['uint16','uint16','uint16','uint16']},
        0x300:{'data_types':['uint16','uint16','uint16','uint16']},
        }


    dll=load_dll("can_dll.dll") #Загрузка DLL

    a = CanWorker(dll,pps,"192.168.7.2",psw="1")
    con=a.connect("192.168.7.2", 2000)
    print(f'Connect to PLC {con}')

    a.callback_func = CALLBACK_FUNC(a.get_pdo)
    a.register_callbac_pdo(a.callback_func)

    a.callback_func_error = CALLBACK_FUNC(a.get_error)
    a.register_callbac_error(a.callback_func_error)

    SDO_w_error=0
    SDO_w_count=0

    SDO_r_error=0
    SDO_r_count=0

    max_count_sdo=5001

    node = 12 # Номер узла к которому обрщаемся
    index = 0x6411 # Индекс SDO объекта (значение канала)
    subindex = 0x00 # Под индекс SDO объекта (номер канала)


    if con > 0:
        logger.info(f"Начинаем отправку heartbeat")
        a.Start_heartbeat(500)
        time.sleep(5)
        
        sdo_on=False
        
        
        # блок записи/чтения SDO параметров
        for i1 in range(1,max_count_sdo):

            value_for_write=[i1,i1,i1,i1]
            res,pdo_data = a.packing_pdo(ppw[0x200],value_for_write)
            if not sdo_on:
                a.WritePDO(node_id=12, number_pdo=0x200, pdo_data=pdo_data)
            else:
                for channel in range(1,9):
                    result_SDO=a.WriteSDO(node_id=node, index=index, sub_index=channel, data=i1, data_type='uint16', timeout_ms=200)
                    SDO_w_count+=1
                    if result_SDO<0:
                        SDO_w_error+=1
                    print(f"Result SDO Write channel:{channel} value:{result_SDO}")

                    result_SDO=a.ReadSDO(node_id=node, index=index, sub_index=channel, timeout_ms=200)
                    SDO_r_count+=1
                    if result_SDO<0:
                        SDO_r_error+=1
                    print(f"Result SDO Read channel:{channel} value:{result_SDO}")
            #time.sleep(0.1)
        
        

        # смотрим сколько ошибок накопилось 
        print(f"SDO_w_error {SDO_w_error}/{SDO_w_count} SDO_r_error {SDO_r_error}/{SDO_r_count}")

        # блок чтения PDO
        t1= datetime.datetime.now()
        while True:        
            t2= datetime.datetime.now()
            if (t2 - t1).total_seconds()  < 2000.0:
                time.sleep(0.2)
                continue
            else:
                break
            

        a.Disconnect()
        a.DestroyWorker()

