#ifndef _CARTOGRAPHER_ROS_MSGS_MSG_STATUSRESPONSE_H
#define _CARTOGRAPHER_ROS_MSGS_MSG_STATUSRESPONSE_H

#include <iostream>
#include <string>

using namespace std;

namespace cartographer_ros_msgs
{
  namespace msg
  {
    class StatusResponse
    {
    public:
      uint32_t cntPub = 0;
      uint32_t cntSub = 0;
      uint32_t idxSerialized = 0;

      typedef std::pair<bool, uint32_t> FragCopyReturnType;

      template <class T>
      uint32_t copyPrimToFragBufLocal(uint8_t *&addrPtr,
                                      const uint32_t cntPub,
                                      const uint32_t size,
                                      const T &data)
      {
        uint32_t lenPad = (0 == (cntPub % sizeof(T))) ? 0 : (sizeof(T) - (cntPub % sizeof(T))); // this doesn't get along with float128.
        if (size < sizeof(T))
        {
          // There are no enough space.
          return 0;
        }
        // Put padding space
        for (int i = 0; i < lenPad; i++)
        {
          *addrPtr = 0;
          addrPtr += 1;
        }
        // Store serialzed value.
        memcpy(addrPtr, &data, sizeof(T));
        addrPtr += sizeof(T);

        return sizeof(T) + lenPad;
      }

      template <class T>
      FragCopyReturnType copyArrayToFragBufLocal(uint8_t *&addrPtr,
                                                 const uint32_t size,
                                                 T &data,
                                                 uint32_t &cntPubMemberLocal)
      {
        uint32_t pubDataSize = data.size();
        uint32_t cntLocalFrag = 0;

        if (cntPubMemberLocal < sizeof(uint32_t))
        {
          if (size < sizeof(uint32_t))
          {
            return {false, 0};
          }
          memcpy(addrPtr, &pubDataSize, sizeof(uint32_t));
          addrPtr += sizeof(uint32_t);
          cntPubMemberLocal += sizeof(uint32_t);
          cntLocalFrag += sizeof(uint32_t);
        }

        uint32_t cntFrag = (cntPubMemberLocal - sizeof(uint32_t));
        // cntPubMemberLocal > 4 here
        uint32_t tmp = std::min(pubDataSize - cntFrag, size - cntLocalFrag);
        if (0 < tmp)
        {
          memcpy(addrPtr, data.data() + cntFrag, tmp);
          addrPtr += tmp;
          cntPubMemberLocal += tmp;
          cntLocalFrag += tmp;
        }

        return {(cntPubMemberLocal - sizeof(uint32_t)) >= pubDataSize, cntLocalFrag};
      }

      uint8_t code;

      string message;

      uint32_t copyToBuf(uint8_t *addrPtr)
      {
        uint32_t tmpPub = 0;
        uint32_t arraySize;
        uint32_t stringSize;

        memcpy(addrPtr, &code, 1);
        addrPtr += 1;
        cntPub += 1;

        if (cntPub % 4 > 0)
        {
          for (int i = 0; i < (4 - (cntPub % 4)); i++)
          {
            *addrPtr = 0;
            addrPtr += 1;
          }
          cntPub += 4 - (cntPub % 4);
        }
        stringSize = message
                         .size();
        memcpy(addrPtr, &stringSize, 4);
        addrPtr += 4;
        cntPub += 4;
        memcpy(addrPtr, message.c_str(), stringSize);
        addrPtr += stringSize;
        cntPub += stringSize;

        return cntPub;
      }

      uint32_t copyFromBuf(const uint8_t *addrPtr)
      {
        uint32_t tmpSub = 0;
        uint32_t arraySize;
        uint32_t stringSize;

        memcpy(&code, addrPtr, 1);
        addrPtr += 1;
        cntSub += 1;

        if (cntSub % 4 > 0)
        {
          for (int i = 0; i < (4 - (cntSub % 4)); i++)
          {
            addrPtr += 1;
          }
          cntSub += 4 - (cntSub % 4);
        }
        memcpy(&stringSize, addrPtr, 4);
        addrPtr += 4;
        cntSub += 4;
        message
            .resize(stringSize);
        memcpy(&message
                   [0],
               addrPtr, stringSize);
        addrPtr += stringSize;
        cntSub += stringSize;

        return cntSub;
      }

      void memAlign(uint8_t *addrPtr)
      {
        if (cntPub % 4 > 0)
        {
          addrPtr += cntPub;
          for (int i = 0; i < (4 - (cntPub % 4)); i++)
          {
            *addrPtr = 0;
            addrPtr += 1;
          }
          cntPub += 4 - (cntPub % 4);
        }
        return;
      }

      uint32_t getTotalSize()
      {
        uint32_t tmpCntPub = cntPub;
        cntPub = 0;
        return tmpCntPub;
      }

      uint32_t getPubCnt()
      {
        return cntPub;
      }

      uint32_t calcRawTotalSize()
      {
        // TODO: store template code here
        return 0;
      }

      uint32_t calcTotalSize()
      {
        uint32_t tmp;
        tmp = 4 // CDR encoding version.
              + calcRawTotalSize();
        tmp += (0 == (tmp % 4) ? // Padding
                    0
                               : (4 - (tmp % 4)));
        return tmp;
      }

      void resetCount()
      {
        cntPub = 0;
        cntSub = 0;
        idxSerialized = 0;
        // TODO: store template code here
        return;
      }

      FragCopyReturnType copyToFragBuf(uint8_t *addrPtr, uint32_t size)
      {
        // TODO: store template code here
        return {false, 0};
      }

    private:
      std::string type_name = "cartographer_ros_msgs::msg::dds_::StatusResponse";
    };
  };
}

namespace message_traits
{
  template <>
  struct TypeName<cartographer_ros_msgs::msg::StatusResponse *>
  {
    static const char *value()
    {
      return "cartographer_ros_msgs::msg::dds_::StatusResponse_";
    }
  };
}

#endif
