#ifndef _CARTOGRAPHER_ROS_MSGS_MSG_SUBMAPQUERY_RESPONSE_H
#define _CARTOGRAPHER_ROS_MSGS_MSG_SUBMAPQUERY_RESPONSE_H

#include <iostream>
#include <string>
#include <vector>
#include "cartographer_ros_msgs/msg/status_response.hpp"
#include "geometry_msgs/msg/pose.hpp"

using namespace std;

namespace cartographer_ros_msgs
{
  namespace msg
  {
    class SubmapQuery_Response
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

      cartographer_ros_msgs::msg::StatusResponse status;

      int32_t submap_version;

      // uint8_t textures;

      uint32_t copyToBuf(uint8_t *addrPtr)
      {
        uint32_t tmpPub = 0;
        uint32_t arraySize;
        uint32_t stringSize;

        tmpPub = status
                     .copyToBuf(addrPtr);
        cntPub += tmpPub;
        addrPtr += tmpPub;

        if (cntPub % 4 > 0)
        {
          for (int i = 0; i < (4 - (cntPub % 4)); i++)
          {
            *addrPtr = 0;
            addrPtr += 1;
          }
          cntPub += 4 - (cntPub % 4);
        }

        memcpy(addrPtr, &submap_version, 4);
        addrPtr += 4;
        cntPub += 4;

        memcpy(addrPtr, &textures, 1);
        addrPtr += 1;
        cntPub += 1;

        return cntPub;
      }

      // cartographer_ros_msgs/SubmapTextureの構造体を宣言
      struct SubmapTexture
      {
        std::vector<uint8_t> cells;
        int32_t width;
        int32_t height;
        double resolution;
        geometry_msgs::msg::Pose slice_pose;
      };

      std::vector<SubmapTexture> textures;

      std::vector<uint8_t>
          cells;
      int32_t width;
      int32_t height;
      double resolution;
      geometry_msgs::msg::Pose slice_pose;

      uint32_t copyFromBuf(const uint8_t *addrPtr)
      {
        uint32_t tmpSub = 0;
        uint32_t arraySize;
        uint32_t arraySize2;
        uint32_t stringSize;

        tmpSub = status
                     .copyFromBuf(addrPtr);
        cntSub += tmpSub;
        addrPtr += tmpSub;

        if (cntSub % 4 > 0)
        {
          for (int i = 0; i < (4 - (cntSub % 4)); i++)
          {
            addrPtr += 1;
          }
          cntSub += 4 - (cntSub % 4);
        }

        memcpy(&submap_version, addrPtr, 4);
        addrPtr += 4;
        cntSub += 4;

        // Textureの配列サイズを取得 基本的には1なのでスキップ
        memcpy(&arraySize2, addrPtr, 4);
        addrPtr += 4;
        cntSub += 4;
        textures.resize(arraySize2);

        //  cartographer_ros_msgs/SubmapTexture[] textures
        /*
          uint8[] cells
          int32 width
          int32 height
          float64 resolution
          geometry_msgs/Pose slice_pose //mROSにある型
        */

        for (int size = 0; size < arraySize2; size++)
        {
          // cells配列サイズを取得
          memcpy(&arraySize, addrPtr, 4);
          addrPtr += 4;
          cntSub += 4;
          // msg_size = arraySize;

          textures[size].cells.resize(arraySize);
          // 具体的なデータを取得
          for (int i = 0; i < arraySize; i++)
          {
            memcpy(&(textures[size].cells[i]), addrPtr, 1);
            addrPtr += 1;
            cntSub += 1;
          }

          printf("after cells cntSub: %ld,arraySize: %ld \n", cntSub, arraySize);

          if (cntSub % 4 > 0)
          {
            for (int i = 0; i < (4 - (cntSub % 4)); i++)
            {
              addrPtr += 1;
            }
            cntSub += 4 - (cntSub % 4);
          }
          printf("after cells alignment 4 cntSub: %d\n", cntSub);

          // memcpy(&textures, addrPtr, 1);
          // addrPtr += 1;
          // cntSub += 1;
          // int32_t width;
          memcpy(&textures[size].width, addrPtr, 4);
          addrPtr += 4;
          cntSub += 4;
          // int32_t height;
          memcpy(&textures[size].height, addrPtr, 4);
          addrPtr += 4;
          cntSub += 4;

          /*_Float64 resolution;*/

          // 8byte alignment
          if (cntSub % 8 > 0)
          {
            for (int i = 0; i < (8 - (cntSub % 8)); i++)
            {
              addrPtr += 1;
            }
            cntSub += 8 - (cntSub % 8);
          }

          memcpy(&textures[size].resolution, addrPtr, 8);
          addrPtr += 8;
          cntSub += 8;
          // geometry_msgs::msg::Pose slice_pose;
          tmpSub = textures[size].slice_pose.copyFromBuf(addrPtr);
          cntSub += tmpSub;
          addrPtr += tmpSub;
        }

        // // cells配列サイズを取得
        // memcpy(&arraySize, addrPtr, 4);
        // addrPtr += 4;
        // cntSub += 4;
        // // msg_size = arraySize;

        // cells.resize(arraySize);
        // // 具体的なデータを取得
        // for (int i = 0; i < arraySize; i++)
        // {
        //   memcpy(&(cells[i]), addrPtr, 1);
        //   addrPtr += 1;
        //   cntSub += 1;
        // }

        // // アライメント
        // // if (cntSub % 2 > 0)
        // // {
        // //   for (int i = 0; i < (2 - (cntSub % 2)); i++)
        // //   {
        // //     addrPtr += 1;
        // //   }
        // //   cntSub += 2 - (cntSub % 2);
        // // }
        // printf("after cells cntSub: %ld,arraySize: %ld \n", cntSub, arraySize);

        // if (cntSub % 4 > 0)
        // {
        //   for (int i = 0; i < (4 - (cntSub % 4)); i++)
        //   {
        //     addrPtr += 1;
        //   }
        //   cntSub += 4 - (cntSub % 4);
        // }
        // printf("after cells alignment 4 cntSub: %d\n", cntSub);

        // // memcpy(&textures, addrPtr, 1);
        // // addrPtr += 1;
        // // cntSub += 1;
        // // int32_t width;
        // memcpy(&width, addrPtr, 4);
        // addrPtr += 4;
        // cntSub += 4;
        // // int32_t height;
        // memcpy(&height, addrPtr, 4);
        // addrPtr += 4;
        // cntSub += 4;

        // /*_Float64 resolution;*/

        // // 8byte alignment
        // if (cntSub % 8 > 0)
        // {
        //   for (int i = 0; i < (8 - (cntSub % 8)); i++)
        //   {
        //     addrPtr += 1;
        //   }
        //   cntSub += 8 - (cntSub % 8);
        // }

        // memcpy(&resolution, addrPtr, 8);
        // addrPtr += 8;
        // cntSub += 8;
        // // geometry_msgs::msg::Pose slice_pose;
        // tmpSub = slice_pose.copyFromBuf(addrPtr);
        // cntSub += tmpSub;
        // addrPtr += tmpSub;

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
      std::string type_name = "cartographer_ros_msgs::msg::dds_::SubmapQuery_Response";
    };
  };
}

namespace message_traits
{
  template <>
  struct TypeName<cartographer_ros_msgs::msg::SubmapQuery_Response *>
  {
    static const char *value()
    {
      return "cartographer_ros_msgs::msg::dds_::SubmapQuery_Response_";
    }
  };
}

#endif
