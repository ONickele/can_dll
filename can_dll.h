//can_dll.h
#include <cstdint>

const int minor_ver_socket = 2;             //минорная версия (minor version) Winsock.
const int major_ver_socket = 2;             //мажорная версия (major version) Winsock.
const int socket_init_success = 0;          //инициализация сокета прошла успешно

const int protocol_socket = 0;              //протокол по умолчанию

const int udp_len_package = 16;             //длинна используемых в canopen udp пакетов

const int empty_data = 0;                   //используется для заполнения массивов пустыми значениями

const int succes_verify = 1;                //успешная верификация SDO пакета

const int num_byte_len_payload_sdo = 8;     //номер байта количества значимых байт в sdo пакете
const int first_byte_data_sdo_w = 12;       //номер байта пакета для копирования данных в пакет SDO

const int first_byte_sdo_read_r = 12;       //первый байт данных payload sdo пакета для передачи в выходной массив функции
const int last_byte_sdo_read_r = 16;        //первый байт данных payload sdo пакета для передачи в выходной массив функции
const int distination_byte_sdo_read_r = 1;  //номер байта назначения копирования payload
const int num_byte_len_payload_sdo_r = 0;   //номер байта количества значимых байт в выходном массиве


const int zero_len = 0;                     //нулевая длина пакета для формирования заголовка


const int mask_cobid = 0xFF;                //маска для преобразования cobid

const int len_uint8 = 8;                    //длина uint8
const int second_cobid_byte = 0;            //номер второго байта cobid
const int first_cobid_byte = 1;             //номер первого байта cobid

const int num_byte_second_index = 9;        //номер байта второго байта индекса sdo
const int num_byte_dirst_index = 10;        //номер байта первого байта индекса sdo
const int num_byte_subindex = 11;           //номер байта сабинтдекса sdo

const int mask_convert_16t08 = 0xFF;        //маска для преобразования uint16 в uint8

const uint8_t num_byte_len_pdo_package = 4;     //номер байта длины payload pdo пакета
const int num_byte_payload_pdo = 8;         //номер байта куда записываются данные  

const int send_cobid = 0x600;               //ID пакета отправки. Используется для отправки данных с указанным идентификатором.
const int receive_cobid = 0x580;            //ID пакета получения. Используется для приема данных с указанным идентификатором.

 
const int id_plc = 0x78;                    //id ПЛК для отправки heartbeat
const int id_heartbeat = 0x7;               //id пакета canopen heartbeat
const int len_heartbeat = 0x1;              //длина пакета hearbeat
const int hearbeat_value = 0x05;            //значение hearbeat
                                            // пакет для отправки запроса
unsigned char heartbeat[udp_len_package] = {id_plc, id_heartbeat, 0, 0, len_heartbeat, 0, 0, 0, hearbeat_value, 0, 0, 0, 0, 0, 0, 0};

const int data_not_exist = 0;               //нет данных на сокете

const int min_cobid_pdo = 0x181;            //минимальный cobid pdo пакета
const int max_cobid_pdo = 0x57F;            //максимальный cobid pdo пакета

const int num_sdo_command = 8;              //номер байта комманды sdo пакета
const int sdo_command_read = 0x60;          //команда ответа sdo пакета чтения

const int num_len_sdo = 4;                  //номер байта длины sdo пакета
const int len_sdo = 8;                      //длина sdo пакета

const int min_command_sdo_w = 0x43;         //минимальное количество действительных байт в ответно sdo пакете чтения параметра
const int max_command_sdo_w = 0x53;         //максимальное количество действительных байт в ответно sdo пакете чтения параметра

const int min_cobid_error = 0x81;           //минимальный cobid пакета ошибки/информации
const int max_cobid_error = 0xFF;           //максимальный cobid пакета ошибки/информации

const int num_pdo_buffer_len_payload = 2;   //номер байта количества значимых байт
const int num_pdo_buffer_payload = 3;       //номер байта начала значимых байт

const int first_cobid_outer_buf = 0;        //номер первого байта cobid для выходного массива
const int second_cobid_outer_buf = 1;       //номер второго байта cobid для выходного массива

const int num_byte_error_payload = 2;       //номер байта для записи пакета error

const int command_write_payload_sdo = 0x23; //максимальное количество значимых байт в команде записи
const int max_count_byte_payload = 4;       //максимальная длина данных для sdo пакета
const int shift_command_len_payload = 2;    //сдвиг для формирования команды записи с учетом протокола canopen
const int command_sdo_read = 0x40;          //команда чтения sdo
