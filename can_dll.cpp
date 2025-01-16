

#include <winsock2.h>
#include <windows.h>
#include <iostream>
#include <cstring>
#include <cstdint>
#include <thread>
#include <functional>

#pragma comment(lib, "ws2_32.lib")


#define IS_ANSWER true
#define IS_REQUEST false

// Определение типа callback-функции
typedef void (*CallbackFunc)(unsigned char*);


extern "C" {
    class Worker {
    public:
        /**
            * @brief Конструктор класса.
            * @param pdobuffer Буфер куда передаются PDO пакеты.
        */
        Worker():callback_pdo(nullptr),callback_error(nullptr), udpSocket(INVALID_SOCKET), isConnected(false) { 
        } // конструктор


        /**
            * @brief Деконструктор класса.
        */
        ~Worker() { // деконструктор 
            if (isConnected) {
                closesocket(udpSocket);
                WSACleanup();
                isConnected = false;
            }
        }

        /**
            * @brief Метод регистрации callback'а получения PDO пакета
            * @param cb функция которую будем привязывать
        */
        int RegisterCallback_pdo(CallbackFunc cb) {
            callback_pdo = cb;
            return 1;
        }

        /**
            * @brief Метод регистрации callback'а получения пакета ошибки
            * @param cb функция которую будем привязывать
        */
        int RegisterCallback_error(CallbackFunc cb) {
            callback_error = cb;
            return 1;
        }

        /**
            * @brief Метод создания сокета.
            * @return 1 - сокет успешно создан, -1 - ошибка инициализации winsock, -2 - ошибка создания сокета.
        */
        int CreateSocket() { // создаем сокет 
            WSADATA wsaData;
            if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) { //инициируем использование winsock DLL процессом
                return -1;
            }
            udpSocket = socket(AF_INET, SOCK_DGRAM, 0);
            if (udpSocket == INVALID_SOCKET) {
                WSACleanup();
                return -2;
            }
            return 1;
        }


        /**
            * @brief Метод подключения к UDP-серверу.
            * @param ipAddress IP-адрес сервера.
            * @param port порт сервера.
            * @return 1 - успешно -1 - сокет уже создан -2 - возникла ошибка при отправке стартового пакета -3 - возникла ошибка при получении ответа.
        */
        int ConnectToUDPServer(const char* ipAddress, int port) {
            if (udpSocket == INVALID_SOCKET) return -1; // проверяем не создан ли сокет 

            // настраиваем сокет 
            serverAddr.sin_family = AF_INET;
            serverAddr.sin_port = htons(port);
            serverAddr.sin_addr.s_addr = inet_addr(ipAddress);

            char zeroBytes[16] = {0}; // создаем массив на отправку в socat для начала обмена 
            int sendResult = sendto(udpSocket, zeroBytes, sizeof(zeroBytes), 0, (sockaddr*)&serverAddr, sizeof(serverAddr));
            if (sendResult == SOCKET_ERROR) { // отправляем наш стартовый пакет 
                closesocket(udpSocket);
                WSACleanup();
                return -2;
            }

            // таймаут ожидания первого пакета от socat 
            DWORD timeout = 2000; 
            setsockopt(udpSocket, SOL_SOCKET, SO_RCVTIMEO, (const char*)&timeout, sizeof(timeout));

            
            char recvBuffer[16]; // буфер для получения ответа от сервера
            int serverAddrSize = sizeof(serverAddr);

            // проверяем что связь действительно установлена и к нам пошли пакеты 
            int recvResult = recvfrom(udpSocket, recvBuffer, sizeof(recvBuffer), 0, (sockaddr*)&serverAddr, &serverAddrSize);
            if (recvResult == SOCKET_ERROR) {
                closesocket(udpSocket);
                WSACleanup();
                return -3; // нас наебали, расходимся 
            }

            // создаем поток прослушивания сокета если не возникло ошибок с установлением связи 
            isConnected = true;
            readThread = std::thread(&Worker::PacketListener, this);
            //heartbeatThread = std::thread(&Worker::Sending_heartbeat, this);
            
            return 1;
        }

        /**
            * @brief Метод создания, отправки и получения SDO пакетов для записи.
            * @param receiverId ID узла назначения.
            * @param index Индекс SDO объекта.
            * @param subIndex Сабиндекс SDO объекта.
            * @param data Массив данных для записи в SDO объект.
            * @param dataSize Размер данных для записи в SDO объект.
            * @param timeout_ms Таймаут ожидания ответа в миллисекундах.
            * @return 1 - успешно -1 - не подключены -2 - ошибка записи -4 нет ответа.
        */
        int WriteSDO(int receiverId, int index, int subIndex, const unsigned char* data, int dataSize, int timeout_ms = 1000) {
            if (!isConnected) return -1;// мы все еще подключены

            // формируем SDO пакет для записи 
            unsigned char sdoPacket[16] = {0}; // массив байт для формирования пакетов 

            makeSDOhead(sdoPacket, true, receiverId, index, subIndex, dataSize); //формируем запрос

            std::memcpy(&sdoPacket[12], data, dataSize); // записываем данные в пакет SDO

            int sendResult = sendto(udpSocket, (char*)sdoPacket, sizeof(sdoPacket), 0, (sockaddr*)&serverAddr, sizeof(serverAddr)); // отправляем наш пакет
            if (sendResult == SOCKET_ERROR) return -2; // не смогли отправить

            // таймер реализованный через тики, chrono ругается
            DWORD start = GetTickCount(); //записываем количество тиков на старте
            while (true) { // обращаемся в общему буферу чтения и проверяем что нам пришел ответ на наш запрос
                if (verifySDO(readBuffer_sdo_w, receiverId, index, subIndex) == 1) { // проверяем что пришел ответ на наш запрос

                        memset(readBuffer_sdo_w, 0, sizeof(readBuffer_sdo_w)); // очищаем буфер ответов записи чтобы не путаться если отправим такой же запрос
                        return 1;
                    }
                if (GetTickCount() - start >= static_cast<DWORD>(timeout_ms)) return -4; //не нашли пакет в течении таймаута
            }
        }

        /**
            * @brief Метод создания, отправки и получения SDO пакетов для чтения.
            * @param receiverId ID узла назначения.
            * @param index Индекс SDO объекта.
            * @param subIndex Сабиндекс SDO объекта.
            * @param outBuffer Массив для хранения данных, полученных из SDO объекта (передаем количество значимых байт и данные в пакете).
            * @param timeout_ms Таймаут ожидания ответа в миллисекундах.
            * @return 1 - успешно -1 - не подключены -2 - ошибка записи -4 нет ответа.
        */
        int ReadSDO(int receiverId, int index, int subIndex, unsigned char* outBuffer, int timeout_ms = 1000) {
            if (!isConnected) return -1; //мы всё еще подключены

            unsigned char sdoPacket[16] = {0}; //пакет для отправки запроса

            makeSDOhead(sdoPacket, false, receiverId, index, subIndex, 0); //формируем запрос

            // отправляем
            int sendResult = sendto(udpSocket, (char*)sdoPacket, sizeof(sdoPacket), 0, (sockaddr*)&serverAddr, sizeof(serverAddr)); // отправляем наш пакет
            if (sendResult == SOCKET_ERROR) return -2;// не смогли отправить

            //запускаем таймер ожидания ответа
            DWORD start = GetTickCount();
            while (true) { //проверяем что пришел ответ на наш запрос
                if (verifySDO(readBuffer_sdo_r, receiverId, index, subIndex) == 1) { // проверяем что пришел ответ на наш запрос 

                    outBuffer[0] = readBuffer_sdo_r[8]; // записываем количество значимых байт для преобразования
                    std::copy(readBuffer_sdo_r + 12, readBuffer_sdo_r + 16, outBuffer + 1); //записываем дату в выходной массив
                    memset(readBuffer_sdo_r, 0, sizeof(readBuffer_sdo_r)); // очищаем буфер ответов чтения чтобы не путаться если отправим такой же запрос
                    return 1;
                    }
                if (GetTickCount() - start >= static_cast<DWORD>(timeout_ms)) return -4; // не нашли пакет в течении таймаута
            }
        }
        
        /**
         * @brief Метод создания, отправки PDO пакетов.
         * @param receiverId ID узла назначения.
         * @param numberPDO Номер PDO. 
         * @param data Массив данных для записи в PDO.
         * @param dataSize Количество действительных байт.
        */
        int WritePDO(int receiverId, int numberPDO, const unsigned char* data, int dataSize) {
            if (!isConnected) return -1;
            
            unsigned char pdoPacket[16] = {0}; // пакет для отправки запроса
            int cobid = numberPDO + receiverId;
            pdoPacket[0] = static_cast<uint8_t>(cobid & 0xFF); // id получателя
            pdoPacket[1] = static_cast<uint8_t>((cobid) >> 8);
            pdoPacket[4] = dataSize; // количество значимых байт
            std::memcpy(&pdoPacket[8], data, dataSize); // записываем данные в пакет PDO
            int sendResult = sendto(udpSocket, (char*)pdoPacket, sizeof(pdoPacket), 0, (sockaddr*)&serverAddr, sizeof(serverAddr));
            if (sendResult == SOCKET_ERROR) return -2; // не смогли отправить
            return 1;

        }

        /**
            * @brief Метод для старта выдачи heartbeat.
            * @param period_ms Период выдачи heartbeat в миллисекундах.
        */
        int Start_heartbeat(int period_ms) {
            period_heartbeat_ms = period_ms;
            send_heartbeat = true;
            return 1;
        };

        /**
            * @brief Метод для остановки выдачи heartbeat.
        */
        int Stop_heartbeat() {
            send_heartbeat = false;
            return 1;
        };

        /**
            * @brief Метод завершения сеанса связи, остановка потока чтения и закрытия сокета.
            * @return 1 - успешно -1 - не подключены.
        */
        int Disconnect() {
            if (isConnected) {
                isConnected = false;
                if (readThread.joinable()) { // проверяем что можем завершить поток
                    readThread.join(); // Дожидаемся завершения потока
                }
                if (heartbeatThread.joinable()) { // проверяем что можем завершить поток
                    heartbeatThread.join(); // Дожидаемся завершения потока
                }
                closesocket(udpSocket); // закрываем сокет
                WSACleanup(); // завершаем операции сокетов
            } else {
                return -1; 
            }
            return 1;
        }

    private:
        /**
            * Экземпляр сокета для приема/отправки данных.
        */
        SOCKET udpSocket;
        /**
            * Структура адреса сервера для UDP-соединения. 
            * Содержит адрес и порт для подключения к серверу.
        */
        sockaddr_in serverAddr;

        /**
            * Флаг активности подключения. 
            * Если значение true, соединение установлено и активно.
        */
        bool isConnected;

        /**
            * Поток для чтения данных. 
            * Поток используется для асинхронного получения данных через сокет.
        */
        std::thread readThread;

        /**
            * Поток для отправки heartbeat
        */
        std::thread heartbeatThread;

        /**
            * Общий буфер чтения. Буфер, в который записываются получаемые данные. 
            * Используется для дальнейшего распределения пакетов SDO чтения и записи.
        */
        unsigned char readBuffer[16];

        /**
            * Буфер для хранения принятых PDO пакетов.
        */
        //unsigned char* pdobuffer;

        unsigned char pdobuffer[16];

        /**
            * Буфер для передачи ошибок с шины.
        */
        //unsigned char* errorbuffer;
        unsigned char errorbuffer[16];

        /**
        * Буфер для записи SDO пакетов ответа на запись. 
        * Этот буфер используется для хранения ответа запроса на запись.
        */
        unsigned char readBuffer_sdo_w[16];

        /**
            * Буфер для записи SDO пакетов ответа на чтение. 
            * Этот буфер используется для хранения ответа запроса на чтение.
        */
        unsigned char readBuffer_sdo_r[16];

        /**
            * ID пакета отправки.
            * Используется для отправки данных с указанным идентификатором.
            * Значение по умолчанию: 0x600.
        */
        const int SEND_COBID = 0x600;

        /**
            * ID пакета получения.
            * Используется для приема данных с указанным идентификатором.
            * Значение по умолчанию: 0x580.
        */
        const int RECEIVE_COBID = 0x580;

        /**
         * Период выдачи heartbeat
        */
        int period_heartbeat_ms = 1000;

        bool send_heartbeat = false;

        /**
         * Callback для получения pdo пакета.
        */
        CallbackFunc callback_pdo;

        /**
         * Callback для получения ошибки с шины.
        */
        CallbackFunc callback_error;

        /**
            * @brief Метод прослушивания сокета и распределения пакетов SDO/PDO.
        */
        void PacketListener() {
            uint16_t can_id;
            fd_set readSet;
            

            timeval timeout;
            timeout.tv_sec = 0;
            timeout.tv_usec = 50000;  // 50 ms

            unsigned char heartbeat[16] = {0}; // пакет для отправки запроса
            heartbeat[0] = 0x78; // id получателя
            heartbeat[1] = 0x7; // heartbeat cobid
            heartbeat[4] = 1; // длинна пакета
            heartbeat[8] = 0x05; // hearbeat

            DWORD start = GetTickCount();

            while (isConnected) {
                // проверяем доступность данных
                FD_ZERO(&readSet); // настраеваем фд для работы select
                FD_SET(udpSocket, &readSet);
                int result = select(0, &readSet, nullptr, nullptr, &timeout);

                //данные доступны
                if (result > 0 && FD_ISSET(udpSocket, &readSet)) {
                    int serverAddrSize = sizeof(serverAddr);
                    int recvResult=recvfrom(udpSocket, (char*)readBuffer, sizeof(readBuffer), 0, (sockaddr*)&serverAddr, &serverAddrSize);
                    if (recvResult == SOCKET_ERROR) {
                        Disconnect(); 
                    }
                    if (recvResult >= 16){ // получили данные
                        can_id = (static_cast<uint16_t>(readBuffer[1]) << 8) | readBuffer[0]; //считаем cobid из двух байт принятого пакета
                        //if ((can_id >= 0x180 && can_id <= 0x57F) && (can_id & 0x80) ) {// Проверяем что это PDO
                        if ((can_id >= 0x180 && can_id <= 0x57F)) {// Проверяем что это PDO
                            GetPDO(); // Записываем во внешний массив pdobuffer
                        } else if (readBuffer[8] == 0x60) {
                            GetSDO(IS_ANSWER); // Записываем ответ в очередь ответов для SDO записи
                        } else if (readBuffer[4] == 8 && readBuffer[8] <= 0x53 &&  readBuffer[8] >= 0x43) {
                            GetSDO(IS_REQUEST); // Записываем ответ в очередь ответов для SDO чтения
                        } else if (can_id >= 0x80 && can_id < 0xFF) {
                            GetError(); // Записываем ошибку во внешний массив errorbuffer
                        }
                    }
                    
                }

                if (send_heartbeat){
                    if (GetTickCount() - start >= static_cast<DWORD>(period_heartbeat_ms)) {
                        sendto(udpSocket, (char*)heartbeat, sizeof(heartbeat), 0, (sockaddr*)&serverAddr, sizeof(serverAddr));
                        start = GetTickCount();
                    }
                }
            }
        }

        /**
            * @brief Метод записи данных пакета во внешний буфер pdobuffer (передается cobid, длина значимых байт и сам payload)
            * @return 1 - успешно -1 - не подключены.
        */
        int GetPDO() {
            if (!isConnected) return -1;
            pdobuffer[0] = readBuffer[0]; // первая часть cobid
            pdobuffer[1] = readBuffer[1]; // вторая часть cobid
            pdobuffer[2] = readBuffer[4]; // длина значимых байт
            std::copy(readBuffer + 8,readBuffer + 16, pdobuffer+3); // записываем содержимое PDO

            if (callback_pdo) {
                callback_pdo(pdobuffer);
            }
            
            return 1;
        }

        /**
            * @brief Метод распределения ответов SDO на массивы ответов SDO записи/чтения.
            * @param rw_rd - Флаг чтения или записи чтобы понять в какой массив закидывать ответ
            * @return 1 - успешно -1 - не подключены.
        */
        int GetSDO(bool rw_rd) {
            if (!isConnected) return -1;

            if (rw_rd) {
                std::copy(readBuffer, readBuffer + 16, readBuffer_sdo_w);
            } else {
                std::copy(readBuffer, readBuffer + 16, readBuffer_sdo_r);
            }
            
            return 1;
        }

        /**
         * @brief Метод получения кода ошибки
         * @return 1 - успешно.
        */
        int GetError() {

            errorbuffer[0] = readBuffer[0]; // первая часть cobid
            errorbuffer[1] = readBuffer[1]; // вторая часть cobid
            std::copy(readBuffer + 8,readBuffer + 16, errorbuffer+2); // записываем содержимое пакета ошибки
            if (callback_error) {
                callback_error(errorbuffer);
            }
            return 1;
        }
        /**
            * @brief Метод создания заголовка SDO пакета.
            * @param package Массив в котором формируется пакет.
            * @param write Флаг чтения или записи.
            * @param receiverId Id получателя.
            * @param index Индекс SDO объекта.
            * @param subIndex Под индекс SDO объекта.
            * @param dataSize Количество байт данных (используется только для вариантта записи).
            * @return 1 - успешно -1 - не подключены.
        */
        int makeSDOhead(unsigned char* package, bool write, int receiverId, int index, int subIndex, int dataSize) {
            if (!isConnected) return -1;

            package[0] = receiverId; // id получателя
            package[1] = static_cast<uint8_t>((SEND_COBID) >> 8);
            package[4] = 8; // длинна пакета
            if (write) {
                package[8] = 0x23 | ((4 - dataSize) << 2); // количество действительных байт исходя из длины 
            } else {
                package[8] = 0x40; // команда чтения
            }
            package[9] = index & 0xFF; // вторая часть индекса
            package[10] = (index >> 8) & 0xFF; // первая часть индекса
            package[11] = subIndex; // под индекс 
            
            return 1;
        }

        /**
            * @brief Метод верификации ответа на наш запрос SDO.
            * @param package Массив в котором находится пакет.
            * @param receiverId Id получателя которому отправляли запрос.
            * @param index Индекс SDO объекта.
            * @param subIndex Под индекс SDO объекта.
            * @return 1 - наш пакет -1 - НЕ наш пакет.
        */
        int verifySDO(unsigned char* package, int receiverId, int index, int subIndex) {

            uint16_t can_id = (static_cast<uint16_t>(package[1]) << 8) | package[0]; //считаем cobid из двух байт принятого пакета

            if (can_id == receiverId | RECEIVE_COBID && // проверяем cobid пакета slave + master
                package[9] == (index & 0xFF) && //первая часть индекса
                package[10] == ((index >> 8) & 0xFF) && // вторая часть индекса
                package[11] == subIndex) { //сабиндекс

                return 1;
            } else {
                return -1;
            }
        }

    };


    // обертки методов для экспорта в dll
    __declspec(dllexport) int CreateSocket(Worker* instance) {
        return instance->CreateSocket();
    }

    __declspec(dllexport) int ConnectToUDPServer(Worker* instance, const char* ipAddress, int port) {
        return instance->ConnectToUDPServer(ipAddress, port);
    }

    __declspec(dllexport) int WriteSDO(Worker* instance, int receiverId, int index, int subIndex, const unsigned char* data, int dataSize, int timeout_ms = 1000) {
        return instance->WriteSDO(receiverId, index, subIndex, data, dataSize, timeout_ms);
    }

    __declspec(dllexport) int ReadSDO(Worker* instance, int receiverId, int index, int subIndex, unsigned char* outBuffer, int timeout_ms) {
        return instance->ReadSDO(receiverId, index, subIndex, outBuffer, timeout_ms);
    }

    __declspec(dllexport) int WritePDO(Worker* instance, int receiverId, int numberPDO, const unsigned char* data, int dataSize) {
        return instance->WritePDO(receiverId, numberPDO, data, dataSize);
    }

    __declspec(dllexport) int Start_heartbeat(Worker* instance, int period_ms) {
        return instance->Start_heartbeat(period_ms);
    }

    __declspec(dllexport) int Stop_heartbeat(Worker* instance) {
        return instance->Stop_heartbeat();
    }

    __declspec(dllexport) int RegisterCallback_pdo(Worker* instance, CallbackFunc callback) {
        return instance->RegisterCallback_pdo(callback);
    }

    __declspec(dllexport) int RegisterCallback_error(Worker* instance, CallbackFunc callback) {
        return instance->RegisterCallback_error(callback);
    }

    __declspec(dllexport) int Disconnect(Worker* instance) {
        return instance->Disconnect();
    }

    __declspec(dllexport) Worker* CreateWorker() {
        return new Worker();
    }

    __declspec(dllexport) void DestroyWorker(Worker* worker) {
        delete worker;
    }
}