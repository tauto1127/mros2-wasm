#ifndef _CARTOGRAPHER_ROS_MSGS_MSG_SUBMAPLIST_H
#define _CARTOGRAPHER_ROS_MSGS_MSG_SUBMAPLIST_H

#include <iostream>
#include <string>
#include "geometry_msgs/msg/pose.hpp"

using namespace std;

namespace cartographer_ros_msgs
{
  namespace msg
  {
    class SubmapList
    {
    public:
      uint32_t cntPub = 0;
      uint32_t cntSub = 0;
      uint32_t idxSerialized = 0;

      geometry_msgs::msg::Pose pose;

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

      int32_t sec;
      uint32_t nanosec;
      string frame_id;

      // submap stuct を宣言
      struct submap_list
      {
        int32_t trajectory_id;
        int32_t submap_index;
        int32_t submap_version;
        geometry_msgs::msg::Pose pose;
        bool is_frozen;
      };

      std::vector<submap_list> submap;

      int32_t trajectory_id;
      int32_t submap_index;
      int32_t submap_version;
      // geometry_msgs/Pose pose
      // int32_t submap;
      bool is_frozen;

      uint32_t copyToBuf(uint8_t *addrPtr)
      {
        uint32_t tmpPub = 0;
        uint32_t arraySize;
        uint32_t stringSize;

        if (cntPub % 4 > 0)
        {
          for (int i = 0; i < (4 - (cntPub % 4)); i++)
          {
            *addrPtr = 0;
            addrPtr += 1;
          }
          cntPub += 4 - (cntPub % 4);
        }

        memcpy(addrPtr, &sec, 4);
        addrPtr += 4;
        cntPub += 4;

        memcpy(addrPtr, &nanosec, 4);
        addrPtr += 4;
        cntPub += 4;

        stringSize = frame_id.size();
        memcpy(addrPtr, &stringSize, 4);
        addrPtr += 4;
        cntPub += 4;
        memcpy(addrPtr, frame_id.c_str(), stringSize);
        addrPtr += stringSize;
        cntPub += stringSize;

        if (cntPub % 4 > 0)
        {
          for (int i = 0; i < (4 - (cntPub % 4)); i++)
          {
            *addrPtr = 0;
            addrPtr += 1;
          }
          cntPub += 4 - (cntPub % 4);
        }

        memcpy(addrPtr, &submap, 4);
        addrPtr += 4;
        cntPub += 4;

        return cntPub;
      }

      std::vector<uint8_t> data;
      uint8_t msg_size;

      uint32_t copyFromBuf(const uint8_t *addrPtr)
      {
        uint32_t tmpSub = 0;
        uint32_t arraySize;
        uint32_t stringSize;

        // header
        if (cntSub % 4 > 0)
        {
          for (int i = 0; i < (4 - (cntSub % 4)); i++)
          {
            addrPtr += 1;
          }
          cntSub += 4 - (cntSub % 4);
        }
        memcpy(&sec, addrPtr, 4);
        addrPtr += 4;
        cntSub += 4;

        memcpy(&nanosec, addrPtr, 4);
        addrPtr += 4;
        cntSub += 4;

        memcpy(&stringSize, addrPtr, 4);
        addrPtr += 4;
        cntSub += 4;
        frame_id.resize(stringSize);
        memcpy(&frame_id[0], addrPtr, stringSize);
        addrPtr += stringSize;
        cntSub += stringSize;

        if (cntSub % 4 > 0)
        {
          for (int i = 0; i < (4 - (cntSub % 4)); i++)
          {
            addrPtr += 1;
          }
          cntSub += 4 - (cntSub % 4);
        }

        // submap[]
        /*
          int32 trajectory_id
          int32 submap_index
          int32 submap_version
          geometry_msgs/Pose pose
          bool is_frozen
        */
        memcpy(&arraySize, addrPtr, 4);
        addrPtr += 4;
        cntSub += 4;
        submap.resize(arraySize);

        for (int i = 0; i < arraySize; i++)
        {
          memcpy(&submap[i].trajectory_id, addrPtr, 4);
          addrPtr += 4;
          cntSub += 4;
          memcpy(&submap[i].submap_index, addrPtr, 4);
          addrPtr += 4;
          cntSub += 4;
          memcpy(&submap[i].submap_version, addrPtr, 4);
          addrPtr += 4;
          cntSub += 4;

          // pose
          tmpSub = submap[i].pose.copyFromBuf(addrPtr);
          cntSub += tmpSub;
          addrPtr += tmpSub;
          // is_frozen
          memcpy(&submap[i].is_frozen, addrPtr, 1);
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
        }

        // memcpy(&trajectory_id, addrPtr, 4);
        // addrPtr += 4;
        // cntSub += 4;
        // memcpy(&submap_index, addrPtr, 4);
        // addrPtr += 4;
        // cntSub += 4;
        // memcpy(&submap_version, addrPtr, 4);
        // addrPtr += 4;
        // cntSub += 4;

        // // pose
        // tmpSub = pose.copyFromBuf(addrPtr);
        // cntSub += tmpSub;
        // addrPtr += tmpSub;
        // // is_frozen
        // memcpy(&is_frozen, addrPtr, 1);

        // // memcpy(&submap, addrPtr, 4);
        // // addrPtr += 4;
        // // cntSub += 4;

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
      std::string type_name = "cartographer_ros_msgs::msg::dds_::SubmapList";
    };
  };
}

namespace message_traits
{
  template <>
  struct TypeName<cartographer_ros_msgs::msg::SubmapList *>
  {
    static const char *value()
    {
      return "cartographer_ros_msgs::msg::dds_::SubmapList_";
    }
  };
}

#endif
