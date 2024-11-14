import ctypes
from ctypes import c_char_p, c_int, c_void_p,c_ubyte, POINTER
from ctypes import util
import os
from cffi import FFI
import struct
import numpy as np
import threading
import paramiko

import datetime
import time


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
        print("DLL не найдена, проверьте путь.")
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
        print("DLL не найдена, проверьте путь и зависимости.")
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
        dll.CreateWorker.argtypes = [POINTER(c_ubyte)]

        dll.DestroyWorker.argtypes = [POINTER(c_void_p)]

        dll.CreateSocket.argtypes = [POINTER(c_void_p)]
        dll.CreateSocket.restype = c_int

        dll.ConnectToUDPServer.argtypes = [POINTER(c_void_p), c_char_p, c_int]
        dll.ConnectToUDPServer.restype = c_int

        dll.WriteSDO.argtypes = [POINTER(c_void_p), c_int, c_int, c_int, POINTER(c_ubyte), c_int, c_int]
        dll.WriteSDO.restype = c_int

        dll.ReadSDO.argtypes = [POINTER(c_void_p), c_int, c_int, c_int, POINTER(c_ubyte), c_int]
        dll.ReadSDO.restype = c_int

        dll.Disconnect.argtypes = [POINTER(c_void_p)]
        dll.Disconnect.restype = c_int
        return 1
    else:
        return -1





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
    except (OverflowError, ValueError):
        return False

class CanWorker():
    def __init__(self, dll: ctypes.CDLL, pdo_objects: dict, pdo_buffer: c_ubyte, ssh_ip: str, ssh_port: int=22, usr: str='root', psw: str='zeon'):
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
        self.worker_instance = self.dll.CreateWorker(pdo_buffer) # создаем экземпляр класса Worker для работы с сокетом
        self.isConnected = False # флаг наличия подключения

        self.pdo_objects = pdo_objects # записываем наши ожидаемые PDO 
        self.pdo_cobids=pps.keys() # записываем нужные cobid 

        self.__ip = ssh_ip
        self.___port = ssh_port
        self.__usr = usr
        self.__psw = psw

    def __del__(self):
        """
        Деструктор, уничтожает экземпляр Worker в dll при удалении объекта.
        """
        self.dll.DestroyWorker(self.worker_instance)


    # подключение ssh для запска socat и отключения nftables
    def __sshconnect(self, port: int) -> int:
        """
        Устанавливает SSH-соединение для запуска socat и отключения nftables.

        @param port: Порт для подключения по SSH.
        @return: 1 если подключение успешно, -1 в случае ошибки.
        """

        self.__shhclient=paramiko.SSHClient()
        self.__shhclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            print(f'Подключаемся к ПЛК по ssh на порт {port}')
            self.__shhclient.connect(hostname=self.__ip, username=self.__usr, password=self.__psw, port=self.___port)
            stdin, stdout, stderr = self.__shhclient.exec_command('systemctl stop nftables') # 🥂🥂 рубим сетевой экран нахой он нам не нужон 🥂🥂
            time.sleep(2)
            stdin, stdout, stderr = self.__shhclient.exec_command(f'socat INTERFACE:can0,pf=29,type=3,prototype=1 UDP-LISTEN:{port},fork')  # 🥂🥂 запускаем socat can->UDP 🥂🥂
            self.__shhclient.close()
            time.sleep(3)
            return 1
        except:
            print('не удалось подключиться к ПЛК')
            return -1

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
            if self.connect_to_udp_server(ip_address, port)>0:
                print('подключились к ПЛК')
                return 1
            else:
                # если не получилось пробуем отрубить nftables и запустить сокат
                print(f"не удалось подключиться к ПЛК, попытка {count+1} из {max_count}")
                if self.__sshconnect(port)<0:
                    return -1
            count+=1
        else:
            return -1

    # пробуем подключиться к udp серверу
    def connect_to_udp_server(self, ip_address: str, port: int) -> int:
        """
        Подключение к UDP серверу.

        @param ip_address: IP-адрес сервера.
        @param port: Порт сервера.
        @return: 1 если подключение успешно, -1 в случае ошибки, -2 если уже подключено.
        """

        if not self.isConnected:
            if (self.dll.CreateSocket(self.worker_instance) > 0):
                res = self.dll.ConnectToUDPServer(self.worker_instance, ip_address.encode('utf-8'), port)
                if res > 0:
                    self.isConnected = True
                return res
            else:
                return -1
        else:
            return -2

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
        if self.isConnected:
            match data_type:
                case 'uint8':
                    if data < 0xFF: # проверяем что данные поместятся при преобразовании 
                        data_send = (c_ubyte * 1)(*data.to_bytes(1, byteorder='little'))
                        data_size = 1
                    else:
                        return -5
                case 'uint16':
                    if data < 0xFFFF: # проверяем что данные поместятся при преобразовании 
                        data_send = (c_ubyte * 2)(*data.to_bytes(2, byteorder='little'))
                        data_size = 2
                    else:
                        return -5
                case 'uint32':
                    if data < 0xFFFFFFFF: # проверяем что данные поместятся при преобразовании 
                        data_send = (c_ubyte * 4)(*data.to_bytes(4, byteorder='little'))
                        data_size = 4
                    else:
                        return -5
                case 'float32': 
                    if is_convertible_to_float32(data): # проверяем что данные поместятся при преобразовании 
                        data_send=bytearray(struct.pack("f", data))
                        data_size = 4
                    else:
                        return -5
                    
            write_result = self.dll.WriteSDO(self.worker_instance, node_id, index, sub_index, data_send, data_size, timeout_ms)
            return write_result
        else:
            return -2
    
    def ReadSDO(self, node_id: int, index: int, sub_index: int, timeout_ms: int) -> int | float:
        """
        Читает данные из объекта SDO.

        @param node_id: Идентификатор узла.
        @param index: Индекс объекта.
        @param sub_index: Подиндекс объекта.
        @param timeout_ms: Время ожидания в миллисекундах.
        @return: Прочитанные данные или код ошибки.
        """

        if self.isConnected:
            buf_len = 16
            buffer = (c_ubyte * 5)()
            read_result = self.dll.ReadSDO(self.worker_instance, node_id, index, sub_index, buffer, timeout_ms)
            if read_result > 0:
                len_data = (buffer[0] ^ 0x43)>>2
                return int.from_bytes(buffer[1:len_data+1], "little")

            else:
                return read_result
        else:
            return -2
    def ReadPDO(self,pdo_buffer: c_ubyte):
        """
        Чтение данных из PDO в отдельном потоке.

        @param pdo_buffer: Буфер для получения данных PDO.
        @return: Поток чтения.
        """
        if self.isConnected:
            t = threading.Thread(target=self.__call_readPDO,args=(pdo_buffer,16),daemon=True)
            t.start()
            return t
        else:
            return -2

    def Stop_ReadPDO(self,th : threading.Thread):
        """
        Останавливает процесс чтения PDO.

        @param th: Поток для остановки.
        """
        self.dll.Stop_ReadPDO(self.worker_instance)
        if th.is_alive():
            th.join()

    def __call_readPDO(self,pdo_buffer: c_ubyte,size_buff: int):
        """
        Метод для вызова функции из dll.

        @param pdo_buffer: Буфер для получения данных.
        @param size_buff: Размер буфера.
        @return: Результат чтения.
        """

        read_result = self.dll.ReadPDO(self.worker_instance,pdo_buffer,size_buff)
        return read_result


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
                    print(f"ошибка в длинне пакета ожидалось {int(sum(self.pdo_objects[cobid]['mapping'])/8)} пришло {data[2]}")
                return node, hex(number_pdo), params
    
    def Disconnect(self):
        """
        Отключает соединение и ставит  флаг isConnected в False..
        """
        self.dll.Disconnect(self.worker_instance)
        self.isConnected = False
    
    def DestroyWorker(self):
        """
        Уничтожает экземпляр Worker и очищает ресурсы.
        """
        self.dll.DestroyWorker(self.worker_instance)
    
pps={0x18C:{'mapping':[8,8,8,8,32],'data_types':['uint8','uint8','uint8','uint8','float32']},
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



dll=load_dll("can_dll.dll") #Загрузка DLL

pdo_buffer = (c_ubyte * 11)() # Буфер куда будет скидываться 
a = CanWorker(dll,pps,pdo_buffer,"192.168.7.2")
res=a.connect("192.168.7.2", 2000)
print(f'Connect to PLC {res}')
SDO_w_error=0
SDO_r_error=0

max_count_sdo=5001
if res > 0:
    value=15555
    for i1 in range(1,max_count_sdo):
        for i in range(1,9):
            result_SDO=a.WriteSDO(12,0x6411,i,i1,'uint16',200)
            if result_SDO<0:
                SDO_w_error+=1
            print(f"Result SDO Write {result_SDO}")

            result_SDO=a.ReadSDO(12,0x6411,i,200)
            if result_SDO<0:
                SDO_r_error+=1
            print(f"Result SDO Read {result_SDO}")


    l_pdo_buffer = (c_ubyte * 11)()
    print(f"SDO_w_error {SDO_w_error}/{max_count_sdo-1} SDO_r_error {SDO_r_error}/{max_count_sdo-1}")
    t1= datetime.datetime.now()
    value = 0
    while True:
        
        t2= datetime.datetime.now()
        if (t2 - t1).total_seconds()  < 20.0:
            #print(pdo_buffer[:])
            pdo = a.parse_pdo(pdo_buffer)
            if pdo:
                print(pdo)
            else:
                print(f"неудача node {int.from_bytes(pdo_buffer[0:2], "little")} пакет {pdo_buffer[:]}")
            
        else:
            break
        l_pdo_buffer[:] = pdo_buffer[:]
        value+=10
        time.sleep(0.2)

    a.Disconnect()
    a.DestroyWorker()

